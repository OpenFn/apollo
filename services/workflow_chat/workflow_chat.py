import json
import os
import re
import uuid
import unicodedata
from typing import List, Optional, Dict, Any
import yaml
from dataclasses import dataclass
from models import resolve_model

_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_dir, "gen_project_config.yaml")) as _f:
    _service_config = yaml.safe_load(_f)

_MODEL = resolve_model(_service_config.get("model", "claude-sonnet"))

# JSON schema for structured outputs — guarantees valid JSON from the API
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "yaml": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"}
            ]
        },
        "text": {"type": "string"}
    },
    "required": ["yaml", "text"],
    "additionalProperties": False
}

# Subagent mode (called from global_chat): adds a "handover" field so the model
# can hand a misrouted request back to the caller. It comes FIRST so it is
# generated before yaml/text — streaming can then suppress output and the
# router reroutes before the user sees anything.
_SUBAGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "handover": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"}
            ]
        },
        **_OUTPUT_SCHEMA["properties"]
    },
    "required": ["handover", "yaml", "text"],
    "additionalProperties": False
}
from anthropic import (
    Anthropic,
    APIConnectionError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    UnprocessableEntityError,
    RateLimitError,
    InternalServerError,
)
import sentry_sdk
from langfuse import observe, propagate_attributes, get_client as get_langfuse_client
from langfuse_util import should_track, build_tags, build_generation_diff, mask_secrets
from name_rules import (
    MAX_EDGE_KEY_LENGTH,
    MAX_NAME_LENGTH,
    grapheme_length,
    normalize_for_lookup,
    sanitize_name,
    truncate_graphemes,
    unicode_names_enabled,
)
from util import ApolloError, create_logger, add_page_prefix, APOLLO_VERSION
from .gen_project_prompt import build_prompt
from workflow_chat.available_adaptors import get_available_adaptors
from streaming_util import (
    StreamManager,
    STATUS_REVIEWING_WORKFLOW,
    STATUS_NEW_WORKFLOW,
    STATUS_DESIGNING_WORKFLOW,
)

logger = create_logger("workflow_chat")


# Helper function for page navigation
def extract_page_prefix_from_last_turn(history: List[Dict[str, str]]) -> Optional[str]:
    """Extract page prefix from last user message if present."""
    if len(history) < 2:
        return None

    # Second-to-last turn is the last user message
    content = history[-2].get("content", "")

    # Extract [pg:...] prefix if present
    if content.startswith("[pg:") and "]" in content:
        return content[:content.find("]") + 1]

    return None


@dataclass
class Payload:
    """
    Data class for validating and storing input parameters.
    Required fields will raise TypeError if not provided.
    """

    content: Optional[str] = None
    errors: Optional[str] = None
    existing_yaml: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    context: Optional[dict] = None
    api_key: Optional[str] = None
    meta: Optional[str] = None
    stream: Optional[bool] = False
    read_only: Optional[bool] = False
    metrics_opt_in: Optional[bool] = None
    # Subagent mode: set only when called from global_chat, never by direct
    # production callers. Enables the handover response field.
    subagent: Optional[bool] = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """
        Create a Payload instance from a dictionary, validating required fields.
        """

        return cls(
            content=data.get("content"),
            errors=data.get("errors"),
            existing_yaml=data.get("existing_yaml"),
            history=data.get("history", []),
            context=data.get("context"),
            api_key=data.get("api_key"),
            meta=data.get("meta"),
            stream=data.get("stream", False),
            read_only=data.get("read_only", False),
            metrics_opt_in=data.get("metrics_opt_in"),
            subagent=data.get("subagent", False),
        )


@dataclass
class ChatConfig:
    model: str = _MODEL
    max_tokens: int = 16384
    api_key: Optional[str] = None


@dataclass
class ChatResponse:
    content: str
    content_yaml: str
    history: List[Dict[str, str]]
    usage: Dict[str, Any]
    # Subagent mode only: reason the request was handed back to the caller
    handover: Optional[str] = None


class AnthropicClient:
    def __init__(self, config: Optional[ChatConfig] = None):
        self.config = config or ChatConfig()
        self.api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)
        # Holds the finalized YAML sent in the streaming `changes` event. The
        # final response reuses this exact string rather than finalizing again,
        # so restore_components runs once and new-component UUIDs stay identical
        # between the streamed preview and the persisted payload.
        self._streamed_yaml = None
        # Subagent mode: handover reason parsed from the model's response.
        # Set as early as possible while streaming so text output is suppressed.
        self._handover = None

    @staticmethod
    def _unescape_json_string(text):
        """Unescape JSON string escape sequences (e.g. \\n -> newline, \\" -> quote).

        When generating inside a JSON string value, newlines and quotes arrive
        escaped. This converts them back so streamed markdown renders properly.
        """
        try:
            return json.loads(f'"{text}"')
        except (json.JSONDecodeError, ValueError):
            return text

    @observe(name="workflow_chat_generate")
    def generate(
        self,
        content: str = None,
        existing_yaml: str = None,
        errors: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        stream: Optional[bool] = False,
        current_page: Optional[dict] = None,
        read_only: Optional[bool] = False,
        subagent: Optional[bool] = False,
        stream_manager: Optional[StreamManager] = None,
    ) -> ChatResponse:
        """Generate a response using the Claude API. Retry up to 2 times if YAML/JSON parsing fails."""

        with sentry_sdk.start_transaction(name="workflow_generation") as transaction:
            history = history.copy() if history else []

            stream_manager = stream_manager or StreamManager(model=self.config.model, stream=stream)
            
            # Extract and preserve existing components (skip in read-only mode)
            preserved_values = {}
            processed_existing_yaml = existing_yaml

            if existing_yaml and existing_yaml.strip():
                if not read_only:
                    try:
                        yaml_data = yaml.safe_load(existing_yaml)
                        preserved_values, processed_existing_yaml = self.extract_and_preserve_components(yaml_data)
                    except Exception as e:
                        logger.warning(f"Could not parse existing YAML for component extraction: {e}")
                else:
                    # In read-only mode, remove IDs to prevent regurgitation
                    processed_existing_yaml = self.remove_ids_from_yaml(existing_yaml)
            
            with sentry_sdk.start_span(description="build_prompt"):
                system_message, prompt = build_prompt(
                    content=content,
                    existing_yaml=processed_existing_yaml,
                    errors=errors,
                    history=history,
                    read_only=read_only,
                    subagent=subagent
                )

            # Structured outputs config — guarantees valid JSON matching schema
            output_config = {
                "format": {
                    "type": "json_schema",
                    "schema": _SUBAGENT_OUTPUT_SCHEMA if subagent else _OUTPUT_SCHEMA
                },
                "effort": "medium"
            }

            accumulated_usage = {
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

            max_retries = 1
            for attempt in range(max_retries + 1):
                # Reset per attempt so a retry never reuses a prior stream's YAML
                self._streamed_yaml = None
                self._handover = None
                with sentry_sdk.start_span(description="anthropic_api_call"):
                    if stream:
                        logger.info("Making streaming API call")
                        if existing_yaml and existing_yaml.strip():
                            stream_manager.send_thinking(STATUS_REVIEWING_WORKFLOW)
                        else:
                            stream_manager.send_thinking(STATUS_NEW_WORKFLOW + STATUS_DESIGNING_WORKFLOW)

                        text_started = False
                        sent_length = 0
                        accumulated_response = ""

                        with self.client.messages.stream(
                            max_tokens=self.config.max_tokens,
                            messages=prompt,
                            model=self.config.model,
                            system=system_message,
                            output_config=output_config,
                            thinking={"type": "adaptive"}
                        ) as stream_obj:
                            for event in stream_obj:
                                accumulated_response, text_started, sent_length = self.process_stream_event(
                                    event,
                                    accumulated_response,
                                    text_started,
                                    sent_length,
                                    stream_manager,
                                    preserved_values
                                )
                        message = stream_obj.get_final_message()

                        # Flush any remaining buffered text, stripping JSON closing chars
                        if text_started and not self._handover:
                            if sent_length < len(accumulated_response):
                                remaining = accumulated_response[sent_length:]
                                remaining = re.sub(r'"\s*}\s*$', '', remaining)
                                if remaining:
                                    stream_manager.send_text(self._unescape_json_string(remaining))

                    else:
                        logger.info("Making non-streaming API call")
                        message = self.client.messages.create(
                            max_tokens=self.config.max_tokens, messages=prompt, model=self.config.model, system=system_message,
                            output_config=output_config,
                            thinking={"type": "adaptive"}
                        )

                # Track usage from this attempt
                if hasattr(message, "usage"):
                    usage = message.usage.model_dump()
                    for key in accumulated_usage:
                        if key in usage:
                            accumulated_usage[key] += usage[key]

                response_parts = []
                for content_block in message.content:
                    if content_block.type == "text":
                        response_parts.append(content_block.text)

                response = "\n\n".join(response_parts)

                with sentry_sdk.start_span(description="parse_and_format_yaml"):

                    response_text, response_yaml = self.split_format_yaml(response, preserved_values, stream_manager)

                # If YAML parsing succeeded or we're on the last attempt, return the result
                if response_yaml is not None or attempt == max_retries:
                    if self._handover:
                        logger.info(f"workflow_chat handing over: {self._handover}")
                        # Deliberately do NOT end the stream: the caller reroutes
                        # the request and the next agent continues on the same stream.
                        return ChatResponse(
                            content=response_text or "",
                            content_yaml=None,
                            history=history,
                            usage=accumulated_usage,
                            handover=self._handover,
                        )

                    if not response_text:
                        stop_reason = getattr(message, "stop_reason", None)
                        empty_reason = "max_tokens" if stop_reason == "max_tokens" else "no_text_blocks"
                        sentry_sdk.set_tag("stop_reason", stop_reason)
                        sentry_sdk.set_tag("empty_reason", empty_reason)
                        sentry_sdk.set_context("empty_response", {
                            "service": "workflow_chat",
                            "attempts": attempt + 1,
                            "usage": accumulated_usage,
                        })
                        stream_manager.end_stream()
                        if stop_reason == "max_tokens":
                            raise ApolloError(502, "Response truncated", type="OUTPUT_TRUNCATED")
                        raise ApolloError(502, "Model returned no usable text", type="EMPTY_OUTPUT")

                    # Add prefix to content when building history
                    prefixed_content = add_page_prefix(content, current_page)

                    updated_history = history + [
                        {"role": "user", "content": prefixed_content},
                        {"role": "assistant", "content": response_text},
                    ]

                    stream_manager.end_stream()

                    return ChatResponse(
                        content=response_text,
                        content_yaml=response_yaml or None,
                        history=updated_history,
                        usage=accumulated_usage,
                    )

                # Otherwise, log and retry
                logger.warning(f"YAML parsing failed, retrying generation (attempt {attempt+1}/{max_retries})")

    def remove_ids_from_yaml(self, yaml_str):
        """Remove all 'id' fields from YAML to prevent ID regurgitation in read-only mode."""
        if not yaml_str or not yaml_str.strip():
            return yaml_str
        try:
            yaml_data = yaml.safe_load(yaml_str)

            def remove_ids(obj):
                if isinstance(obj, dict):
                    obj.pop("id", None)
                    for v in obj.values():
                        remove_ids(v)
                elif isinstance(obj, list):
                    for item in obj:
                        remove_ids(item)

            remove_ids(yaml_data)
            return yaml.dump(yaml_data, sort_keys=False, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.warning(f"Could not remove IDs from YAML: {e}")
            return yaml_str

    #: Key an edge falls back to when its reference cannot be resolved.
    UNRESOLVED_REFERENCE = "unresolved-step"

    #: Key for an edge whose own key sanitizes away to nothing and which has no
    #: endpoints to derive a label from.
    UNNAMED_EDGE = "edge"

    @staticmethod
    def _resolve_by_name(reference, job_names):
        """Resolve a step reference against job *names*, or None.

        Exact match wins outright. Only if nothing matches exactly does it fall
        back to the lookup fold, and then only when the fold picks out exactly
        one job: `Fetch Patients` and `fetch patients` are two different names
        that fold together, so taking the first fold hit bound the edge to
        whichever happened to come first in the document. An ambiguous
        reference is not resolved at all — a visible dangle beats a silent
        binding to the wrong step.
        """
        if not reference:
            return None

        def unambiguous(matches, how):
            if len(matches) == 1:
                return matches[0]
            if matches:
                logger.warning(
                    f"Step reference {reference!r} {how} {len(matches)} jobs "
                    f"({', '.join(sorted(matches))}); leaving it unresolved rather than guessing",
                )
            return None

        # Exact is not automatically unique: two jobs can arrive sharing a name.
        exact = [key for key, name in job_names.items() if name == reference]
        if exact:
            return unambiguous(exact, "exactly matches the name of")

        wanted = normalize_for_lookup(reference)
        if not wanted:
            return None

        folded = [key for key, name in job_names.items() if normalize_for_lookup(name) == wanted]
        return unambiguous(folded, "matches the folded name of")

    #: Token-shaped text. Used for ONE question only: "is this a swap token we
    #: never issued?" — the degrade branch. Deliberately not used to find our
    #: own tokens: we know exactly which ones we issued, and a pattern can only
    #: guess at their shape.

    @staticmethod
    def _reference_key(value):
        """A mapping key that distinguishes `1`, `"1"` and `True`.

        YAML types keys: `1:` is an int, `"1":` a string, `on:` a boolean.
        Keying a mapping on `str(value)` makes the first two collide; keying it
        on the raw value makes the last two collide, because `hash(True) ==
        hash(1)`. Pairing the type name with the text avoids both.
        """
        return (type(value).__name__, str(value))

    @staticmethod
    def _section(yaml_data, name):
        """Return `yaml_data[name]` as a dict of dicts, or {} if it is anything else.

        `jobs:` with nothing under it parses as None, and a single bare entry
        (`b:`) gives a None value. Both are valid YAML and both used to raise
        somewhere in this pipeline, where the exception was swallowed and the
        user got prose and no workflow.
        """
        if not isinstance(yaml_data, dict):
            return {}
        section = yaml_data.get(name)
        if not isinstance(section, dict):
            return {}
        for key, value in list(section.items()):
            if not isinstance(value, dict):
                section[key] = {}
        return section

    #: Stand-in for a reference that sanitizes away to nothing. Uniquified
    #: against the workflow's own keys at sanitize time, because a user can
    #: perfectly well name a step "unresolved-step" — keys are uniquified
    #: against each other, not against this. An edge carrying the sentinel
    #: stays visibly broken rather than silently binding to a real step.

    @staticmethod
    def _unique_name(candidate: str, taken: set, fallback: str) -> str:
        """Return `candidate` (or `fallback` if it sanitized away) made unique against `taken`.

        Job names and job keys must both be unique within a workflow. Two names
        that differ only in characters the rule strips — `Résumé` and `Resume`
        under the ASCII rule — would otherwise collapse onto each other and the
        second job would overwrite the first.

        The suffix is added inside the length cap, not on top of it: appending
        `-2` to a name that is already at the limit would push it over, and
        Lightning would reject the result.
        """
        candidate = candidate or fallback
        if candidate not in taken:
            taken.add(candidate)
            return candidate

        suffix = 2
        while True:
            tail = f"-{suffix}"
            trimmed = truncate_graphemes(candidate, MAX_NAME_LENGTH - grapheme_length(tail))
            unique = f"{trimmed}{tail}"
            if unique not in taken:
                taken.add(unique)
                return unique
            suffix += 1

    @staticmethod
    def _edge_label(edge_key: str, edge_data: object, remap_reference: object) -> str:
        """Derive an edge's `source->target` label after its endpoints were renamed.

        The label comes from the edge's own `source_*`/`target_*` fields
        wherever it has them, rather than from splitting the old label on "->".
        Under the permissive rule "->" is a legal run of characters inside a
        step name, which makes that split ambiguous — and the fields are the
        real identity anyway; the key is only a label.

        An edge whose endpoints are both known always gets the derived label,
        whatever its old key looked like. Deriving it for `a->b` but leaving
        `e1` alone would mean the sanitizer emits keys its own test assertion
        rejects. Only an edge with no usable endpoints keeps its old key, and
        then it is split on the first "->" if it has one.
        """
        # YAML gives an unquoted `on:` as the boolean True, not a string.
        edge_key = str(edge_key)

        if isinstance(edge_data, dict):
            source = edge_data.get("source_job") or edge_data.get("source_trigger")
            target = edge_data.get("target_job") or edge_data.get("target_trigger")
            if source and target:
                return f"{source}->{target}"

        if "->" not in edge_key:
            # Nothing to derive a label from and no arrow to split on. Still
            # sanitize it — a key carrying a NUL crashes the insert on
            # Lightning's side just as surely as a name would.
            return sanitize_name(edge_key, unicode_names_enabled()) or AnthropicClient.UNNAMED_EDGE

        source_part, target_part = edge_key.split("->", 1)
        return f"{remap_reference(source_part)}->{remap_reference(target_part)}"

    @staticmethod
    def sanitize_job_names(yaml_data: object) -> None:
        """
        Bring every job key, job name, trigger key and edge reference in the
        workflow into line with the active step-name rule (see `name_rules`).

        Keys are rewritten alongside names, and edges are rewritten through the
        resulting key mapping rather than sanitized independently. Sanitizing
        the two separately is how edges used to end up pointing at jobs that no
        longer existed.
        """
        if not isinstance(yaml_data, dict):
            # A non-dict payload is not a workflow. One caller swallows every
            # exception from this, so raising here would silently drop YAML.
            return

        unicode_mode = unicode_names_enabled()

        # One mapping per section, never shared. A workflow may legitimately
        # have a trigger and a job whose original keys are the same string, and
        # a single mapping keyed on that string would let the jobs pass
        # overwrite the trigger's entry — rewriting the edge's source_trigger
        # to point at a job and orphaning the trigger.
        key_mappings = {"jobs": {}, "triggers": {}}

        def sanitize_section(section: str, fallback_prefix: str, label: str) -> dict | None:
            """Sanitize the keys of `jobs:` or `triggers:`, recording the renames."""
            entries = yaml_data.get(section)
            if not isinstance(entries, dict):
                return None

            mapping = key_mappings[section]
            taken = set()
            rebuilt = {}
            renamed = []
            for index, (key, data) in enumerate(entries.items()):
                original = str(key)
                new_key = AnthropicClient._unique_name(
                    sanitize_name(original, unicode_mode), taken, f"{fallback_prefix}-{index + 1}",
                )
                # Keyed on type *and* text; see `_reference_key`.
                mapping[AnthropicClient._reference_key(key)] = new_key
                rebuilt[new_key] = data
                if original != new_key:
                    renamed.append(f"{original!r} -> {new_key!r}")

            if renamed:
                logger.info(f"Sanitized {len(renamed)} {label} key(s): {', '.join(renamed)}")

            yaml_data[section] = rebuilt
            return rebuilt

        triggers = sanitize_section("triggers", "trigger", "trigger")
        jobs = sanitize_section("jobs", "step", "job")

        # Captured before the renaming loop below, so a by-name reference is
        # matched against what the model actually wrote.
        # `str(...)`, not a string-only filter. A model writing `name: 2024`,
        # `name: on` or `name: 01` is ordinary output, and YAML hands those over
        # as an int, a bool and an int. Filtering them out left them unsanitized
        # and unrenamed, and Ecto rejects a `:string` cast from an integer, so a
        # workflow that used to save stopped saving. The `None` case the filter
        # was written for is handled by excluding None explicitly.
        original_job_names = {
            job_key: str(job_data["name"])
            for job_key, job_data in (jobs or {}).items()
            if isinstance(job_data, dict)
            and job_data.get("name") is not None
            and str(job_data["name"]).strip()
        }

        taken_names = set()
        if jobs:
            renamed = []
            for job_key, job_data in jobs.items():
                if isinstance(job_data, dict) and job_data.get("name") is not None:
                    original_name = str(job_data["name"])
                    new_name = AnthropicClient._unique_name(
                        sanitize_name(original_name, unicode_mode), taken_names, job_key,
                    )
                    job_data["name"] = new_name
                    if original_name != new_name:
                        renamed.append(f"{original_name!r} -> {new_name!r}")

            if renamed:
                logger.info(f"Sanitized {len(renamed)} job name(s): {', '.join(renamed)}")

        # The sentinel must not collide with anything a user can type — keys or
        # names. Names count because a dangling edge is reported by name, and a
        # reader matching it against the step list would be misled.
        unresolved = AnthropicClient._unique_name(
            AnthropicClient.UNRESOLVED_REFERENCE,
            set(jobs or {}) | set(triggers or {}) | taken_names,
            AnthropicClient.UNRESOLVED_REFERENCE,
        )

        def remap_reference(reference: object, section: str | None = None) -> str:
            """Map a reference through the mapping for `section` (or either, for a key part).

            `source_job` resolves against jobs and `source_trigger` against
            triggers. An edge *key* part has no field to say which it is, so it
            tries jobs first and then triggers.
            """
            sections = (section,) if section else ("jobs", "triggers")
            for name in sections:
                new_key = key_mappings[name].get(AnthropicClient._reference_key(reference))
                if new_key is not None:
                    return new_key

            # Not a key. The likeliest model mistake is referring to a step by
            # its *name* instead of its key, which otherwise ships as a
            # well-formed edge pointing at nothing.
            if "jobs" in sections and reference is not None:
                by_name = AnthropicClient._resolve_by_name(str(reference), original_job_names)
                if by_name is not None:
                    logger.info(
                        f"Edge referred to step by name {str(reference)!r}; "
                        f"resolved to job key {by_name!r}",
                    )
                    return by_name

            # Genuinely unresolvable. Sanitize it so it at least obeys the rule;
            # if nothing survives, say so rather than leaking the raw value out.
            resolved = sanitize_name(str(reference), unicode_mode) or unresolved

            # If the sanitized form is a real key, that is usually the right
            # answer and not a coincidence: a key with a trailing space, a tab,
            # a NUL, or one written in a different normal form all sanitize to
            # exactly what the model wrote. Only treat it as a collision when
            # the *original* key it belongs to was something else entirely.
            owner = _sanitized_key_owner(resolved, sections)
            if owner is not None:
                if _is_the_same_reference(owner, reference):
                    return resolved
                logger.warning(
                    f"Unresolvable reference {str(reference)!r} sanitizes to {resolved!r}, "
                    f"which belongs to a different step ({owner!r}); using the unresolved "
                    f"marker rather than binding to it",
                )
                resolved = unresolved

            dangling.add(resolved)
            return resolved

        def _sanitized_key_owner(resolved: str, sections: tuple) -> object:
            """Return the original key that `resolved` is the sanitized form of."""
            for name in sections:
                for original, new_key in key_mappings[name].items():
                    if new_key == resolved:
                        return original[1]
            return None

        def _is_the_same_reference(original_key: str, reference: object) -> bool:
            """True if `original_key` and `reference` are the same name written differently.

            Whitespace, control characters and normal form are all differences a
            reader would not see. A genuinely different name is not.

            The length cap is *not* one of them: `normalize_for_lookup` does not
            truncate, so a 150-character key sanitizes to a 100-character one
            that a 100-character reference matches, and this returns False —
            the edge goes to the sentinel. That is a real gap, and it is here
            rather than hidden because the fix belongs in whichever of the two
            should stop caring about length.
            """
            return normalize_for_lookup(original_key) == normalize_for_lookup(str(reference))

        dangling = set()

        edges = yaml_data.get("edges")
        if isinstance(edges, dict):
            sanitized_edges = {}

            remapped_fields = 0

            for edge_key, edge_data in edges.items():
                if isinstance(edge_data, dict):
                    for field, section in (
                        ("source_job", "jobs"),
                        ("target_job", "jobs"),
                        ("source_trigger", "triggers"),
                        ("target_trigger", "triggers"),
                    ):
                        if field in edge_data:
                            original_reference = edge_data[field]
                            edge_data[field] = remap_reference(original_reference, section)
                            if str(original_reference) != edge_data[field]:
                                remapped_fields += 1

                label = AnthropicClient._edge_label(edge_key, edge_data, remap_reference)

                # The label is not unique on its own: two edges may join the
                # same pair of steps (an on_success and an on_failure edge is an
                # ordinary workflow). Keying on the bare label would drop one of
                # them, so disambiguate instead of overwriting, with the suffix
                # *inside* the cap, the same rule `_unique_name` follows.
                sanitized_edge_key = truncate_graphemes(label, MAX_EDGE_KEY_LENGTH)
                suffix = 2
                while sanitized_edge_key in sanitized_edges:
                    tail = f"-{suffix}"
                    trimmed = truncate_graphemes(label, MAX_EDGE_KEY_LENGTH - grapheme_length(tail))
                    sanitized_edge_key = f"{trimmed}{tail}"
                    suffix += 1

                sanitized_edges[sanitized_edge_key] = edge_data

            if remapped_fields:
                logger.info(f"Remapped {remapped_fields} edge endpoint reference(s)")

            if len(sanitized_edges) != len(edges):  # pragma: no cover - defensive
                logger.error(
                    f"Edge count changed while sanitizing: {len(edges)} in, {len(sanitized_edges)} out",
                )

            yaml_data["edges"] = sanitized_edges

        if dangling:
            # A well-formed edge pointing at nothing looks fine to every
            # character check, so it used to ship in silence. It is still
            # emitted — dropping the edge would lose more than it saves — but
            # it is no longer invisible. Only the count goes to Sentry; the
            # names are the caller's own, so they go to the log.
            logger.warning(
                f"Workflow has edge endpoints that match no step or trigger: "
                f"{', '.join(sorted(dangling))}",
            )
            sentry_sdk.capture_message(
                f"Workflow has {len(dangling)} edge endpoint(s) matching no step or trigger",
                level="warning",
            )

    def finalize_yaml(self, parsed_yaml, preserved_values=None):
        """
        Apply the full post-processing pipeline to a parsed workflow dict and
        return the YAML string: validate adaptors, sanitize names, and restore
        preserved IDs/code (placeholders -> real values, or new UUIDs).

        This MUST run before the YAML leaves the service. Both the streaming
        `changes` event and the final response carry the output of this method,
        never the raw __ID_*__ / __CODE_BLOCK_*__ placeholder tokens.
        """
        with sentry_sdk.start_span(description="validate_adaptors"):
            self.validate_adaptors(parsed_yaml)
        with sentry_sdk.start_span(description="sanitize_job_names"):
            self.sanitize_job_names(parsed_yaml)
        with sentry_sdk.start_span(description="restore_components"):
            self.restore_components(parsed_yaml, preserved_values)
        return yaml.dump(parsed_yaml, sort_keys=False, allow_unicode=True)

    def split_format_yaml(self, response, preserved_values=None, stream_manager=None):
        """Split text and YAML in response and format the YAML."""
        output_text, output_yaml = "", None

        try:
            # Try to parse the response as JSON
            response_data = json.loads(response)

            # Subagent mode: a handover means the request is being handed back
            # to the caller — capture the reason and skip the YAML entirely
            if response_data.get("handover"):
                self._handover = response_data["handover"]
                return response_data.get("text", "").strip(), ""

            # Extract text and yaml from the JSON
            output_text = response_data.get("text", "").strip()
            raw_yaml = response_data.get("yaml") or ""

            if raw_yaml and raw_yaml.strip():
                if self._streamed_yaml is not None:
                    # Reuse the YAML already finalized and sent in the streaming
                    # `changes` event so the preview and the persisted payload
                    # are byte-identical (new-component UUIDs can't diverge).
                    output_yaml = self._streamed_yaml
                else:
                    if stream_manager:
                        stream_manager.send_thinking("Formatting workflow...", signature="proxy_formatting_signature")
                    # Parse YAML string into Python object (separate try/except
                    # so bad yaml can't leak through to the response)
                    try:
                        parsed_yaml = yaml.safe_load(raw_yaml)

                        if isinstance(parsed_yaml, dict):
                            output_yaml = self.finalize_yaml(parsed_yaml, preserved_values)
                        else:
                            output_yaml = ""
                    except Exception as e:
                        logger.warning(f"YAML parsing failed, discarding yaml content: {e}")
                        output_yaml = ""
            else:
                output_yaml = ""

        except Exception as e:
            logger.error(f"Error during JSON parsing: {str(e)}")

        return output_text, output_yaml

    def validate_adaptors(self, yaml_data):
        """Validate that all adaptors in the YAML are on the approved list (name only, ignore version)."""

        try:
            available_adaptors = get_available_adaptors()
            valid_adaptor_names = {adaptor["name"] for adaptor in available_adaptors}

            if yaml_data and "jobs" in yaml_data:
                jobs = yaml_data["jobs"]
                for job_key, job_data in jobs.items():
                    if "adaptor" in job_data:
                        adaptor = job_data["adaptor"]
                        # Remove version if present (after last @)
                        base = adaptor.rsplit("@", 1)[0]
                        # Always remove '@openfn/language-' prefix
                        short_name = base[len("@openfn/language-"):]
                        if short_name not in valid_adaptor_names:
                            logger.warning(f"Invalid adaptor found in job '{job_key}': {adaptor}")
        except Exception as e:
            logger.error(f"validate_adaptors encountered an error: {e}")

    @staticmethod
    def extract_and_preserve_components(yaml_data):
        """
        Extract both codes and IDs from all components.
        Returns: (preserved_values, processed_yaml_string)
        """
        if not yaml_data:
            return {}, None
        
        preserved_values = {}
        
        if "jobs" in yaml_data:
            for job_key, job_data in yaml_data["jobs"].items():
                if "body" in job_data:
                    body_content = job_data["body"].strip()
                    if body_content and body_content != "// Add operations here":
                        placeholder = f"__CODE_BLOCK_{job_key}__"
                        preserved_values[placeholder] = body_content
                        job_data["body"] = placeholder
                
                if "id" in job_data:
                    placeholder = f"__ID_JOB_{job_key}__"
                    preserved_values[placeholder] = job_data["id"]
                    job_data["id"] = placeholder
        
        if "triggers" in yaml_data:
            for trigger_key, trigger_data in yaml_data["triggers"].items():
                if "id" in trigger_data:
                    # Store the trigger ID directly without placeholder
                    preserved_values["trigger_id"] = trigger_data["id"]
                    # Remove the id key from what we send to the model
                    del trigger_data["id"]
        
        if "edges" in yaml_data:
            for edge_key, edge_data in yaml_data["edges"].items():
                if "id" in edge_data:
                    placeholder = f"__ID_EDGE_{edge_key}__"
                    preserved_values[placeholder] = edge_data["id"]
                    edge_data["id"] = placeholder
        
        return preserved_values, yaml.dump(yaml_data, sort_keys=False, allow_unicode=True)

    def restore_components(self, yaml_data, preserved_values=None):
        """
        Restore preserved codes and IDs, generate new UUIDs for new components.
        """
        if not yaml_data:
            return
        
        preserved_values = preserved_values or {}
        
        if "jobs" in yaml_data:
            for job_key, job_data in yaml_data["jobs"].items():
                if "body" in job_data:
                    current_body = job_data["body"]
                    if isinstance(current_body, str) and current_body in preserved_values:
                        job_data["body"] = preserved_values[current_body]
                    else:
                        job_data["body"] = "// Add operations here"
                else:
                    job_data["body"] = "// Add operations here"
                
                if "id" in job_data:
                    current_id = job_data["id"]
                    
                    if isinstance(current_id, str) and current_id in preserved_values:
                        job_data["id"] = preserved_values[current_id]
                    elif isinstance(current_id, str) and current_id.startswith("__ID_") and current_id.endswith("__"):
                        msg = f"Unknown placeholder {current_id}, generating new ID"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        job_data["id"] = str(uuid.uuid4())
                else:
                    job_data["id"] = str(uuid.uuid4())
        
        if "triggers" in yaml_data:
            for trigger_key, trigger_data in yaml_data["triggers"].items():
                if "trigger_id" in preserved_values:
                    # Directly restore the preserved trigger ID
                    trigger_data["id"] = preserved_values["trigger_id"]
                elif "id" not in trigger_data:
                    # Generate new ID if no preserved ID exists
                    trigger_data["id"] = str(uuid.uuid4())

        if "edges" in yaml_data:
            for edge_key, edge_data in yaml_data["edges"].items():
                if "id" in edge_data:
                    current_id = edge_data["id"]
                    
                    if isinstance(current_id, str) and current_id in preserved_values:
                        edge_data["id"] = preserved_values[current_id]
                    elif isinstance(current_id, str) and current_id.startswith("__ID_") and current_id.endswith("__"):
                        msg = f"Unknown placeholder {current_id}, generating new ID"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        edge_data["id"] = str(uuid.uuid4())
                else:
                    edge_data["id"] = str(uuid.uuid4())

    def process_stream_event(self, event, accumulated_response, text_started, sent_length, stream_manager, preserved_values=None):
        """
        Process a single stream event from the Anthropic API.

        YAML is generated first (buffered silently), then finalized (IDs/code
        restored) and sent as a changes event, and the text explanation streams
        to the client. The finalized YAML is cached so the final response reuses
        it rather than restoring a second time.
        """
        if event.type == "content_block_delta":
            if event.delta.type == "text_delta":
                text_chunk = event.delta.text
                accumulated_response += text_chunk

                if not text_started:
                    # YAML phase: buffer silently until text starts.
                    # Tolerant of whitespace variants the model may emit.
                    match = re.search(r'"text"\s*:\s*"', accumulated_response)

                    if match:
                        # Close the partial object and extract the fields
                        # generated before "text" (yaml, and in subagent mode
                        # the handover reason, which comes first)
                        yaml_part = accumulated_response[:match.start()]
                        yaml_raw = yaml_part.rstrip().rstrip(",") + "}"
                        try:
                            partial = json.loads(yaml_raw)
                        except (json.JSONDecodeError, ValueError):
                            partial = None
                        if not isinstance(partial, dict):
                            partial = {}

                        if partial.get("handover"):
                            # Handed back to the caller: suppress all output —
                            # the rerouted agent produces the user-facing reply
                            self._handover = partial["handover"]

                        yaml_value = partial.get("yaml")
                        if yaml_value and not self._handover:
                            # Finalize before sending so the streamed preview carries
                            # real IDs/code, not raw placeholders. Cache it so the final
                            # response reuses the identical YAML. Only send if the content
                            # is actually valid YAML (a dict).
                            try:
                                parsed = yaml.safe_load(yaml_value)
                                if isinstance(parsed, dict):
                                    restored_yaml = self.finalize_yaml(parsed, preserved_values)
                                    self._streamed_yaml = restored_yaml
                                    stream_manager.send_changes({"yaml": restored_yaml})
                            except Exception:
                                pass  # Invalid YAML, skip changes event

                        # Mark where text content starts
                        sent_length = match.end()
                        text_started = True

                if text_started and not self._handover:
                    # Text phase: stream with buffer for split escape sequences
                    buffer_size = 2
                    safe_to_send_until = len(accumulated_response) - buffer_size

                    if safe_to_send_until > sent_length:
                        safe_text = accumulated_response[sent_length:safe_to_send_until]
                        stream_manager.send_text(self._unescape_json_string(safe_text))
                        sent_length = safe_to_send_until

        return accumulated_response, text_started, sent_length


@observe(name="workflow_chat", capture_input=False)
def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        # The stream manager is an object rather than data, so it is dropped.
        # Everything else goes through the shared mask instead of a per-service
        # name list, which catches nested values and key-shaped strings too.
        sentry_sdk.set_context(
            "request_data",
            mask_secrets(
                {k: v for k, v in data_dict.items() if k != "_stream_manager"},
            ),
        )

        data = Payload.from_dict(data_dict)

        input_meta = data_dict.get("meta") or {}
        session_id = input_meta.get("session_id") if isinstance(input_meta, dict) else None
        user_info = (input_meta.get("user") or {}) if isinstance(input_meta, dict) else {}
        tracking = should_track(data_dict)

        if tracking:
            langfuse = get_langfuse_client()
            langfuse.update_current_span(input=data.content)

        if data.context is None:
            data.context = {}

        # Construct current_page from context
        page_name = data.context.get("page_name")
        current_page = {
            "type": "workflow",
            "name": page_name
        }

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        with propagate_attributes(
            session_id=session_id,
            user_id=user_info.get("id") if tracking else None,
            tags=build_tags("workflow_chat", user_info) if tracking else None,
            metadata=None if tracking else {"tracing_disabled": "true"},
        ):
            result = client.generate(
                content=data.content,
                existing_yaml=data.existing_yaml,
                errors=data.errors,
                history=data.history,
                stream=data.stream,
                current_page=current_page,
                read_only=data.read_only,
                subagent=data.subagent,
                # In-process callers (global_chat) may inject a shared stream
                # manager so a handed-over request continues the same stream
                stream_manager=data_dict.get("_stream_manager"),
            )

            if tracking:
                diff_meta = build_generation_diff(
                    original=data.existing_yaml,
                    generated=result.content_yaml,
                    yaml_mode=True,
                )
                if diff_meta:
                    langfuse.update_current_span(metadata=diff_meta)

            # Tag the trace when the request was handed back for rerouting to
            # the planner, so we can filter for handovers.
            if tracking and result.handover:
                with propagate_attributes(tags=["handover"]):
                    pass

            # Build response
            response_dict = {
                "response": result.content,
                "response_yaml": result.content_yaml,
                "history": result.history,
                "usage": result.usage,
                "meta": {"apollo_version": APOLLO_VERSION}
            }

            if result.handover:
                response_dict["handover"] = result.handover

            return response_dict

    except ApolloError:
        raise
    except ValueError as e:
        raise ApolloError(400, str(e), type="BAD_REQUEST")

    except APIConnectionError as e:
        raise ApolloError(
            503,
            "Unable to reach the Anthropic AI Service",
            type="CONNECTION_ERROR",
            details={"cause": str(e.__cause__)},
        )
    except AuthenticationError as e:
        raise ApolloError(401, "Authentication failed", type="AUTH_ERROR")
    except RateLimitError as e:
        raise ApolloError(
            429, "Rate limit exceeded, please try again later", type="RATE_LIMIT", details={"retry_after": 60}
        )
    except BadRequestError as e:
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except PermissionDeniedError as e:
        raise ApolloError(403, "Not authorized to perform this action", type="FORBIDDEN")
    except NotFoundError as e:
        raise ApolloError(404, "Resource not found", type="NOT_FOUND")
    except UnprocessableEntityError as e:
        raise ApolloError(422, str(e), type="INVALID_REQUEST")
    except InternalServerError as e:
        raise ApolloError(500, "The Anthropic AI Service encountered an error", type="PROVIDER_ERROR")
    except Exception as e:
        logger.error(f"Unexpected error during chat generation: {str(e)}")
        raise ApolloError(500, str(e))