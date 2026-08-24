"""The attached log reaches the subagent's API call as the exact bytes sent in.

This is the regression guard for
https://github.com/OpenFn/apollo/issues/643 — the planner used to relay only
its own `message` field, so a subagent saw the planner's paraphrase of a log or
nothing at all.

Every LLM call is scripted, so the whole router -> planner -> job_chat chain runs
without a token spent. The attachment carries an improbable canary
(OKAPI_CANARY_...): a paraphrase cannot reproduce it by luck, so `canary in
messages` is a real assertion about the bytes rather than a judgement call about
the wording.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from global_chat.global_chat import main as global_chat_main

# Improbable on purpose: nothing but a verbatim copy of the attachment can
# put this string in front of the model.
CANARY = "OKAPI_CANARY_7f3a91"

LOG = (
    "[R/T] Starting job map-to-dhis2\n"
    f"[JOB] ✗ TypeError: Cannot read properties of undefined (reading '{CANARY}')\n"
    "[R/T] Run finished with errors"
)

WORKFLOW_YAML = """\
name: wf
jobs:
  map-to-dhis2:
    name: Map to DHIS2
    body: |
      fn(state => state);
"""


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, tool_input, block_id="tu_1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def response(content, stop_reason):
    usage = SimpleNamespace(
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    usage.model_dump = lambda: {"input_tokens": 1, "output_tokens": 1}
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class ScriptedAnthropic:
    """Stands in for every agent's Anthropic client, dispatching on the request.

    The three callers are told apart by what they ask for, not by call order, so
    the script does not silently rot if an agent adds a round.
    """

    def __init__(self, *_args, **_kwargs):
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        tool_names = {t["name"] for t in kwargs.get("tools") or []}

        if "call_job_code_agent" in tool_names:
            # The planner: delegate once, then answer.
            planner_rounds = sum(
                1 for c in self.calls if "call_job_code_agent" in {t["name"] for t in c.get("tools") or []}
            )
            if planner_rounds == 1:
                return response(
                    [tool_use_block("call_job_code_agent", {
                        "message": "the mapping step blew up on the run - see the attached log",
                        "job_key": "map-to-dhis2",
                    })],
                    "tool_use",
                )
            return response([text_block("The mapping step read a key nothing produced.")], "end_turn")

        if "edit_job" in tool_names:
            # job_chat, called as a subagent by the planner
            return response([text_block("That key is never set upstream.")], "end_turn")

        # The router's structured routing decision
        return response([text_block('{"destination": "planner", "confidence": 5, "job_key": null}')], "end_turn")

    def job_chat_prompt_text(self):
        """Everything job_chat put in front of the model, as one string.

        System and messages both, since typed context (a run log lands in
        <run_logs>) goes in the system message while the question goes in the
        user turn.
        """
        for call in self.calls:
            if "edit_job" in {t["name"] for t in call.get("tools") or []}:
                return _prompt_text(call)
        raise AssertionError("job_chat was never called")

    def all_prompt_text(self):
        """Everything every agent put in front of a model, as one string."""
        return "\n".join(_prompt_text(call) for call in self.calls)


def _prompt_text(call):
    """Flatten one API call's system + messages into a searchable string."""
    system = call.get("system") or ""
    if isinstance(system, list):
        system = "\n".join(str(block.get("text", block)) for block in system)
    messages = "\n".join(str(m["content"]) for m in call.get("messages") or [])
    return f"{system}\n{messages}"


@pytest.fixture
def scripted():
    client = ScriptedAnthropic()
    with patch("global_chat.router.Anthropic", return_value=client), \
         patch("global_chat.planner.Anthropic", return_value=client), \
         patch("job_chat.job_chat.Anthropic", return_value=client), \
         patch("job_chat.prompt.retrieve_knowledge", return_value={"search_results": []}):
        yield client


def call_global_chat(scripted, attachments, history=None):
    return global_chat_main({
        "content": "why did the last two steps fail?",
        "workflow_yaml": WORKFLOW_YAML,
        "page": "workflows/wf/map-to-dhis2",
        "history": history or [],
        "attachments": attachments,
        "api_key": "test-key",
    })


def test_attached_log_reaches_the_subagents_api_call_verbatim(scripted):
    call_global_chat(scripted, [{"type": "log", "content": LOG}])

    sent = scripted.job_chat_prompt_text()
    assert CANARY in sent, "the planner delegated without passing the attachment through"
    assert LOG in sent, "the log arrived altered, not as the bytes the user attached"
    # ...in the block job_chat already had for logs, not a second one
    assert "<run_logs>" in sent


def test_attachment_is_not_persisted_to_history(scripted):
    result = call_global_chat(scripted, [{"type": "log", "content": LOG}])

    # Nothing the client stores and replays next turn carries the log, so a
    # later turn cannot re-read this run as the current one
    assert all(CANARY not in turn["content"] for turn in result["history"])


def test_oversized_attachment_fails_before_any_model_is_called(scripted):
    """Rejected at the door, not three agents deep.

    An attachment too big for the prompt cannot be answered by any route, so
    there is nothing to gain from paying for the routing call first — and
    nothing is silently trimmed to make it fit.
    """
    from util import ATTACHMENT_TOTAL_CHAR_LIMIT, ApolloError

    huge = "x" * (ATTACHMENT_TOTAL_CHAR_LIMIT + 1)

    with pytest.raises(ApolloError) as excinfo:
        call_global_chat(scripted, [{"type": "log", "content": huge}])

    assert excinfo.value.type == "ATTACHMENT_TOO_LARGE"
    assert scripted.calls == [], "a model was called before the size was checked"


def test_a_later_turn_does_not_resend_an_earlier_attachment(scripted):
    first = call_global_chat(scripted, [{"type": "log", "content": LOG}])

    scripted.calls.clear()
    call_global_chat(scripted, attachments=[], history=first["history"])

    assert CANARY not in scripted.all_prompt_text()
