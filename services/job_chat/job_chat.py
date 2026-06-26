import os
import json
import re
import yaml
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
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
from langfuse_util import should_track, build_tags
from util import ApolloError, create_logger, AdaptorSpecifier, add_page_prefix, APOLLO_VERSION
from .prompt import build_prompt, build_error_correction_prompt
from .old_prompt import build_old_prompt
from streaming_util import (
    StreamManager,
    STATUS_REVIEWING_CODE,
    STATUS_NEW_CODE,
    STATUS_WORKING,
    STATUS_WRITING_CODE,
)
from models import resolve_model

_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_dir, "rag.yaml")) as _f:
    _service_config = yaml.safe_load(_f)

_MODEL = resolve_model(_service_config.get("model", "claude-sonnet"))

logger = create_logger("job_chat")

# JSON schema for structured outputs when suggest_code is True
_CODE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "code_edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "old_code": {"type": "string"},
                    "new_code": {"type": "string"}
                },
                "required": ["action", "new_code"],
                "additionalProperties": False
            }
        },
        "text_answer": {"type": "string"}
    },
    "required": ["code_edits", "text_answer"],
    "additionalProperties": False
}

_EDIT_TOOL = {
    "name": "edit_job",
    "description": (
        "Apply one or more edits to the user's CURRENT job code. Call this ONLY when "
        "the user wants their job changed — never to show an illustrative example "
        "(put examples in your normal text reply instead). Pass ALL edits in a single "
        "call via the `code_edits` array; they are applied in order, each operating on "
        "the result of the previous one. Write your conversational reply as normal text "
        "outside this tool call."
    ),

    "strict": True, # Structured outputs only used for code edits, not the entire model answer.
    "input_schema": {
        "type": "object",
        "properties": {"code_edits": _CODE_OUTPUT_SCHEMA["properties"]["code_edits"]},
        "required": ["code_edits"],
        "additionalProperties": False,
    },
}


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

    content: str
    context: Optional[dict] = None
    api_key: Optional[str] = None
    meta: Optional[str] = None
    suggest_code: Optional[bool] = None
    stream: Optional[bool] = False
    download_adaptor_docs: Optional[bool] = True
    refresh_rag: Optional[bool] = False
    metrics_opt_in: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """
        Create a Payload instance from a dictionary, validating required fields.
        """
        if "content" not in data:
            raise ValueError("'content' is required")

        return cls(
            content=data["content"],
            context=data.get("context"),
            api_key=data.get("api_key"),
            meta=data.get("meta"),
            suggest_code=data.get("suggest_code"),
            stream=data.get("stream", False),
            download_adaptor_docs=data.get("download_adaptor_docs", True),
            refresh_rag=data.get("refresh_rag", False),
            metrics_opt_in=data.get("metrics_opt_in"),
        )


@dataclass
class ChatConfig:
    model: str = _MODEL
    max_tokens: int = 16384
    api_key: Optional[str] = None


@dataclass
class ChatResponse:
    response: str
    suggested_code: Optional[str]
    history: List[Dict[str, str]]
    usage: Dict[str, Any]
    rag: Dict[str, Any]
    diff: Optional[Dict[str, Any]] = None

class AnthropicClient:
    def __init__(self, config: Optional[ChatConfig] = None):
        self.config = config or ChatConfig()
        self.api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)

    @staticmethod
    def _unescape_json_string(text):
        """Unescape JSON string escape sequences (e.g. \\n -> newline, \\" -> quote).

        When suggest_code is true, Claude generates text inside a JSON string value,
        so newlines and quotes arrive escaped. This converts them back to actual
        characters so streamed markdown renders properly.
        """
        try:
            return json.loads(f'"{text}"')
        except (json.JSONDecodeError, ValueError):
            return text

    @observe(name="job_chat_generate")
    def generate(
        self,
        content: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[dict] = None,
        rag: Optional[str] = None,
        suggest_code: Optional[bool] = None,
        stream: Optional[bool] = False,
        download_adaptor_docs: Optional[bool] = True,
        refresh_rag: Optional[bool] = False,
        current_page: Optional[dict] = None
    ) -> ChatResponse:
        """
        Generate a response using the Claude API with optional streaming.
        """
        sentry_sdk.set_tag("prompt_type", "code_suggestions" if suggest_code else "no_code_suggestions")

        with sentry_sdk.start_transaction(name="chat_generation") as transaction:
            history = history.copy() if history else []

            stream_manager = StreamManager(model=self.config.model, stream=stream)
            if context and context.get("expression"):
                stream_manager.send_thinking(STATUS_REVIEWING_CODE)
            else:
                stream_manager.send_thinking(STATUS_NEW_CODE)

            with sentry_sdk.start_span(description="build_prompt"):
                if suggest_code is True:
                    system_message, prompt, retrieved_knowledge = build_prompt(
                        content=content,
                        history=history,
                        context=context,
                        rag=rag,
                        api_key=self.api_key,
                        stream_manager=stream_manager,
                        download_adaptor_docs=download_adaptor_docs,
                        refresh_rag=refresh_rag
                    )

                else:
                    system_message, prompt, retrieved_knowledge = build_old_prompt(
                        content=content,
                        history=history,
                        context=context,
                        rag=rag,
                        api_key=self.api_key,
                        download_adaptor_docs=download_adaptor_docs,
                        refresh_rag=refresh_rag
                        )

            # effort applies to all modes. For suggest_code we expose the `edit_job`
            # tool. tool_choice stays "auto": the model answers in text
            # and only calls the tool when it actually wants to change the job.
            output_config = {"effort": "medium"}
            tool_kwargs = (
                {"tools": [_EDIT_TOOL], "tool_choice": {"type": "auto"}}
                if suggest_code else {}
            )

            with sentry_sdk.start_span(description="anthropic_api_call"):
                if stream:
                    logger.info("Making streaming API call")
                    text_started = False
                    sent_length = 0
                    accumulated_response = ""
                    self._stream_applied = False
                    self._stream_suggested_code = None
                    self._stream_diff = None

                    original_code = context.get("expression") if context and isinstance(context, dict) else None

                    stream_kwargs = dict(
                        max_tokens=self.config.max_tokens,
                        messages=prompt,
                        model=self.config.model,
                        system=system_message,
                        thinking={"type": "adaptive"},
                        output_config=output_config,
                        **tool_kwargs
                    )

                    with self.client.messages.stream(**stream_kwargs) as stream_obj:
                        for event in stream_obj:
                            if event.type == "message_start":
                                stream_manager.send_thinking(STATUS_WORKING)
                            # The edit_job tool block starts after the text ends; its
                            # input (the code) streams silently, so show a status here.
                            elif event.type == "content_block_start" and getattr(getattr(event, "content_block", None), "type", None) == "tool_use":
                                stream_manager.send_thinking(STATUS_WRITING_CODE)
                            accumulated_response, text_started, sent_length = self.process_stream_event(
                                event,
                                accumulated_response,
                                suggest_code,
                                text_started,
                                sent_length,
                                stream_manager,
                                original_code,
                                content
                            )
                    message = stream_obj.get_final_message()

                    # Flush any remaining buffered text, stripping JSON closing chars
                    if suggest_code and text_started:
                        if sent_length < len(accumulated_response):
                            remaining = accumulated_response[sent_length:]
                            remaining = re.sub(r'"\s*}\s*$', '', remaining)
                            if remaining:
                                stream_manager.send_text(self._unescape_json_string(remaining))

                else:
                    logger.info("Making non-streaming API call")
                    create_kwargs = dict(
                        max_tokens=self.config.max_tokens, messages=prompt, model=self.config.model, system=system_message,
                        thinking={"type": "adaptive"},
                        output_config=output_config,
                        **tool_kwargs
                    )
                    message = self.client.messages.create(**create_kwargs)

            if hasattr(message, "usage"):
                if message.usage.cache_creation_input_tokens:
                    logger.info(f"Cache write: {message.usage.cache_creation_input_tokens} tokens")
                if message.usage.cache_read_input_tokens:
                    logger.info(f"Cache read: {message.usage.cache_read_input_tokens} tokens")

            # The model answers in normal text; it calls the `edit_job` tool only
            # when it wants to change the user's job. So text = the reply, and the
            # tool's parsed input carries the code edits (no JSON-in-text parsing).
            text_parts = []
            tool_code_edits = None
            for content_block in message.content:
                if getattr(content_block, "type", None) == "tool_use" and getattr(content_block, "name", None) == "edit_job":
                    tool_code_edits = (content_block.input or {}).get("code_edits") or []
                elif getattr(content_block, "type", None) == "text":
                    text_parts.append(content_block.text)

            text_response = "\n\n".join(text_parts).strip()
            suggested_code = None
            diff = None

            if suggest_code is True and tool_code_edits:
                job_code = context.get("expression") if isinstance(context, dict) else None
                # Apply edits even for an empty job: it's just the blank-file
                # case. See https://github.com/OpenFn/apollo/issues/539.
                with sentry_sdk.start_span(description="apply_code_edits"):
                    suggested_code, diff = self.apply_code_edits(
                        content=content, text_answer=text_response,
                        original_code=job_code or "", code_edits=tool_code_edits,
                    )
                # If the model called the tool but emitted no prose, give the user
                # a short confirmation so the response isn't empty.
                if not text_response and suggested_code:
                    text_response = "I'll update your job code."

            # Visibility: did the model call edit_job, and in what block order?
            # (block order shows whether text came before/after the tool call.)
            if suggest_code is True:
                _blocks = [getattr(b, "type", "?") for b in message.content]
                if tool_code_edits is None:
                    logger.info("edit_job NOT called — text-only answer (blocks=%r)", _blocks)
                else:
                    logger.info(
                        "edit_job CALLED: %d edit(s), patches_applied=%s (blocks=%r)",
                        len(tool_code_edits), (diff or {}).get("patches_applied"), _blocks,
                    )

            # Add prefix to content when building history
            prefixed_content = add_page_prefix(content, current_page)

            updated_history = history + [
                {"role": "user", "content": prefixed_content},
                {"role": "assistant", "content": text_response},
            ]

            usage = self.sum_usage(
                message.usage.model_dump() if hasattr(message, "usage") else {},
                *[usage_data for usage_key, usage_data in retrieved_knowledge.get("usage", {}).items()]
            )

            stop_reason = getattr(message, "stop_reason", None)

            # Check truncation BEFORE the empty check. max_tokens commonly leaves
            # PARTIAL text behind (or partial/broken JSON in suggest_code mode);
            # if we only inspected stop_reason when text_response is empty, that
            # cut-off content would be returned as a normal success and the
            # truncation signal lost. Surface it regardless of whether text came back.
            if stop_reason == "max_tokens":
                sentry_sdk.set_tag("stop_reason", stop_reason)
                sentry_sdk.set_tag("empty_reason", "max_tokens")
                sentry_sdk.set_context("empty_response", {
                    "service": "job_chat",
                    "suggest_code": bool(suggest_code),
                })
                stream_manager.end_stream()
                raise ApolloError(502, "Response truncated", type="OUTPUT_TRUNCATED")

            if not text_response:
                sentry_sdk.set_tag("stop_reason", stop_reason)
                sentry_sdk.set_tag("empty_reason", "no_text_blocks")
                sentry_sdk.set_context("empty_response", {
                    "service": "job_chat",
                    "suggest_code": bool(suggest_code),
                })
                stream_manager.end_stream()
                raise ApolloError(502, "Model returned no usable text", type="EMPTY_OUTPUT")

            stream_manager.end_stream()

            return ChatResponse(
                response=text_response,
                suggested_code=suggested_code,
                history=updated_history,
                usage=usage,
                rag=retrieved_knowledge,
                diff=diff
            )

    def process_stream_event(
        self,
        event,
        accumulated_response,
        suggest_code,
        text_started,
        sent_length,
        stream_manager,
        original_code=None,
        content=None
    ):
        """
        Process a single stream event from the Anthropic API.

        The conversational reply is plain text now. Code edits arrive via the
        `edit_job` tool call (as input_json_delta) and are applied from the final
        message — not streamed here — so we simply forward text deltas live.
        """
        if event.type == "content_block_delta" and event.delta.type == "text_delta":
            text_chunk = event.delta.text
            accumulated_response += text_chunk
            stream_manager.send_text(text_chunk)

        return accumulated_response, text_started, sent_length

    def parse_and_apply_edits(self, response: str, content: str, original_code: Optional[str] = None) -> tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """Parse JSON response and apply code edits to original code."""
        try:
            response_data = json.loads(response)
            text_answer = response_data.get("text_answer", "").strip()
            code_edits = response_data.get("code_edits", [])
            
            if not code_edits:
                return text_answer, None, None

            suggested_code, diff = self.apply_code_edits(content=content, text_answer=text_answer, original_code=original_code or "", code_edits=code_edits)
            return text_answer, suggested_code, diff
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return response, None, None
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return response, None, None

    def apply_code_edits(self, content: str, text_answer: str, original_code: str, code_edits: List[Dict[str, Any]]) -> tuple[Optional[str], Dict[str, Any]]:
        """Apply a list of code edits to the original code."""
        current_code = original_code
        patches_applied = 0
        warnings = []
        
        for edit in code_edits:
            try:
                new_code, edit_applied, warning = self.apply_single_edit(content=content, text_answer=text_answer, code=current_code, edit=edit)
                if new_code is not None:
                    current_code = new_code
                if edit_applied:
                    patches_applied += 1
                if warning:
                    warnings.append(warning)
            except Exception as e:
                logger.warning(f"Failed to apply edit {edit}: {e}")
                warnings.append(f"Failed to apply edit: {str(e)}")
        
        diff = {
            "patches_applied": patches_applied
        }
        
        if warnings:
            diff["warning"] = ". ".join(warnings)
        
        final_code = current_code if patches_applied > 0 else None
        return final_code, diff

    def apply_single_edit(self, content: str, text_answer: str, code: str, edit: Dict[str, Any]) -> tuple[str, bool, Optional[str]]:
        """Apply a single code edit and return (new_code, success, warning)."""

        sentry_sdk.set_context("code_edit_context", {
            "llm_text_answer": text_answer,
            "llm_edit_answer": edit,
        })

        action = edit.get("action")

        # Empty job: there is nothing to edit against, so the new code IS the
        # result regardless of action (replace vs rewrite). Handling this here
        # keeps correctness independent of which action the model picks.
        # See https://github.com/OpenFn/apollo/issues/539.
        if not code.strip():
            new_code = edit.get("new_code")
            if new_code:
                return new_code, True, None

        if action == "replace":
            old_code = edit.get("old_code")
            new_code = edit.get("new_code")
            logger.info(f"attempting this edit: old code: {old_code}\nnew code: {new_code}")
            
            if not old_code or new_code is None:
                msg = "Code edit failed: Replace action requires old_code and new_code"         
            elif old_code not in code:
                msg = "Code edit failed: old_code not found in current code"
            elif code.count(old_code) > 1:
                msg = "Code edit failed: multiple matches"
            else:
                return code.replace(old_code, new_code), True, None

            if msg:
                sentry_sdk.capture_message(msg, level="warning")
                return self.handle_replace_error(content, text_answer, code, edit, msg)
        
        elif action == "rewrite":
            new_code = edit.get("new_code")
            if not new_code:
                warning = "Rewrite code failed, new code missing"
                logger.warning(warning)
                return None, False, warning
            return new_code, True, None
        
        else:
            warning ="Error in applying code edit, invalid action"
            logger.warning(warning)
            return None, False, warning
        
    def handle_replace_error(self, content: str, text_answer: str, code: str, edit: Dict[str, Any], error_message: str) -> tuple[str, bool, str]:
        """Helper to handle replace action errors with correction attempt."""
        old_code = edit.get("old_code")
        new_code = edit.get("new_code")
        corrected_code, success, correction_warning = self.try_error_correction(
            content=content, error_message=error_message, old_code=old_code, 
            new_code=new_code, full_code=code, text_explanation=text_answer
        )

        warning = "Initial error: " + error_message + (f". Correction warning: {correction_warning}" if correction_warning else "")

        if not success:
            sentry_sdk.capture_message(warning, level="error")

        return (corrected_code, success, warning)
        
    @observe(name="job_chat_error_correction")
    def try_error_correction(self, content: str, error_message: str, old_code: str, new_code: str, full_code: str, text_explanation: str) -> tuple[str, bool, Optional[str]]:
        """Try to correct the edit once, return (code, success)."""
        logger.info(f"Code edit error: {error_message}. Attempting correction...")
        
        try:
            system_message, prompt = build_error_correction_prompt(
                content=content,
                error_message=error_message,
                old_code=old_code,
                new_code=new_code,
                full_code=full_code,
                text_explanation=text_explanation
            )
            # structured outputs removed here too (see note in generate); the
            # correction prompt already instructs the {explanation, corrected_*}
            # JSON shape and json.loads below is wrapped in try/except.
            message = self.client.messages.create(
                max_tokens=16384,
                messages=prompt,
                model=self.config.model,
                system=system_message,
                output_config={"effort": "medium"},
                thinking={"type": "adaptive"}
            )

            response = "\n\n".join([block.text for block in message.content if block.type == "text"])
            correction_data = json.loads(response)

            corrected_old = correction_data.get("corrected_old_code")
            corrected_new = correction_data.get("corrected_new_code")
            logger.info(f"Corrector response: {response}")
            
            if corrected_old and corrected_new is not None and corrected_old in full_code:
                warning = None
                if full_code.count(corrected_old) > 1:
                    warning = "Corrected old code appears more than once in the code. Applying edit to first occurrence only."
                    logger.warning(warning)
                logger.info("Successfully applied corrected edit")
                return full_code.replace(corrected_old, corrected_new, 1), True, warning

        except Exception as e:
            warning = f"Error correction failed: {e}"
            logger.warning(warning)
            return None, False, warning
        
        warning = f"Error correction failed. Tried to apply: {correction_data.get('corrected_new_code')}"
        logger.warning(warning)
        return None, False, warning

    def sum_usage(self, *usage_objects):
        """Sum multiple Usage object token counts and return a count dictionary."""
        result = {}
        
        for usage in usage_objects:
            for field in ["cache_creation_input_tokens", "cache_read_input_tokens", "input_tokens", "output_tokens"]:
                value = usage.get(field)
                if value is not None:
                    result[field] = result.get(field, 0) + value
        
        return result



@observe(name="job_chat", capture_input=False)
def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        sentry_sdk.set_context("request_data", {
            k: v for k, v in data_dict.items() if k != "api_key"
            })

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
        adaptor_string = data.context.get("adaptor")

        current_page = {
            "type": "job_code",
            "name": page_name
        }

        if adaptor_string:
            try:
                adaptor = AdaptorSpecifier(adaptor_string)
                current_page["adaptor"] = f"{adaptor.short_name}@{adaptor.version}"
            except Exception as e:
                logger.warning(f"Failed to parse adaptor string '{adaptor_string}': {e}")

        # Extract rag_data from meta if present
        rag_data = input_meta.get("rag") if isinstance(input_meta, dict) else None

        # Detect navigation by comparing current page prefix with last turn's prefix
        current_prefix = add_page_prefix("", current_page).strip()
        last_prefix = extract_page_prefix_from_last_turn(data_dict.get("history", []))
        user_navigated = last_prefix is not None and current_prefix != last_prefix
        should_refresh_rag = data.refresh_rag or user_navigated

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)
        with propagate_attributes(
            session_id=session_id,
            user_id=user_info.get("id") if tracking else None,
            tags=build_tags("job_chat", user_info) if tracking else None,
            metadata=None if tracking else {"tracing_disabled": "true"},
        ):
            result = client.generate(
                content=data.content,
                history=data_dict.get("history", []),
                context=data.context,
                rag=rag_data,
                suggest_code=data.suggest_code,
                stream=data.stream,
                download_adaptor_docs=data.download_adaptor_docs,
                refresh_rag=should_refresh_rag,
                current_page=current_page
            )

            response_dict = {
                "response": result.response,
                "suggested_code": result.suggested_code,
                "history": result.history,
                "usage": result.usage,
                "meta": {"rag": result.rag, "apollo_version": APOLLO_VERSION}
            }

            if result.diff:
                response_dict["diff"] = result.diff

            return response_dict

    except ApolloError:
        raise
    except ValueError as e:
        raise ApolloError(400, str(e), type="BAD_REQUEST")

    except APIConnectionError as e:
        details = {"cause": str(e.__cause__)} if e.__cause__ else {}
        raise ApolloError(
            503,
            "Unable to reach the Anthropic AI Service",
            type="CONNECTION_ERROR",
            details=details,
        )
    except AuthenticationError as e:
        raise ApolloError(401, "Authentication failed", type="AUTH_ERROR")
    except RateLimitError as e:
        retry_after = int(e.response.headers.get('retry-after', 60)) if hasattr(e, 'response') else 60
        raise ApolloError(
            429, "Rate limit exceeded, please try again later", type="RATE_LIMIT", details={"retry_after": retry_after}
        )
    except BadRequestError as e:
        if "prompt is too long" in str(e):
            error_message = "Input prompt exceeds maximum token limit (200,000 tokens). Please reduce the amount of text or context provided."
            raise ApolloError(400, error_message, type="PROMPT_TOO_LONG")
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