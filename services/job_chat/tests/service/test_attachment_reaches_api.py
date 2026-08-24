"""job_chat renders a payload attachment into the request it actually sends.

Service tier: the Anthropic client is mocked, the rest of the handler is real.
The canary (OKAPI_CANARY_...) makes the assertion about bytes rather than
wording — nothing but a verbatim copy can produce it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from job_chat.job_chat import main as job_chat_main

CANARY = "OKAPI_CANARY_4b2e07"
LOG = f"[JOB] ✗ Request failed with status 401 Unauthorized ({CANARY})"


def fake_message():
    """Minimal stand-in for an Anthropic response: one text block, no tool call."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The 401 is a credential problem.")],
        usage=SimpleNamespace(
            model_dump=lambda: {"input_tokens": 1, "output_tokens": 1},
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        stop_reason="end_turn",
    )


def test_payload_attachment_reaches_the_api_call_and_not_the_history():
    """Payload field to the bytes in the request, in one assertion.

    Each hop passing the argument along is the easy part to break silently, so
    this asserts on the request rather than on any intermediate call.
    """
    client = MagicMock()
    client.messages.create.return_value = fake_message()

    with patch("job_chat.job_chat.Anthropic", return_value=client), \
         patch("job_chat.prompt.retrieve_knowledge", return_value={"search_results": []}):
        result = job_chat_main({
            "content": "why did this fail?",
            "context": {},
            "suggest_code": True,
            "api_key": "test-key",
            "attachments": [{"type": "log", "content": LOG}],
        })

    messages = client.messages.create.call_args.kwargs["messages"]
    assert LOG in messages[-1]["content"]

    # ...and the history handed back to the caller carries none of it, so the
    # next turn cannot re-read this log as the current run
    assert all(CANARY not in turn["content"] for turn in result["history"])
