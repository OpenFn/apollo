"""
Langfuse tracing integration test for global_chat.

Runs 2 sequential conversation turns with the same session_id:
  Turn 1: vague request that triggers clarification (no workflow generated)
  Turn 2: specific follow-up that triggers the planner to build a workflow

After the turns, queries Langfuse API to verify traces were created with
correct user_id, tags, and that api_key is not leaked in trace input.
"""
import os
import time
import uuid
import yaml
from dotenv import load_dotenv
from langfuse.api import LangfuseAPI
from .test_utils import call_global_chat_service, print_response_details, get_attachment

load_dotenv()

SESSION_ID = f"test-global-chat-{uuid.uuid4().hex[:8]}"
USER_ID = f"test-user-{uuid.uuid4().hex[:8]}"


def _get_api_client():
    """Create a Langfuse REST API client from environment variables."""
    return LangfuseAPI(
        base_url=os.environ["LANGFUSE_BASE_URL"],
        username=os.environ["LANGFUSE_PUBLIC_KEY"],
        password=os.environ["LANGFUSE_SECRET_KEY"],
    )


def _fetch_traces(session_id, retries=5, delay=3):
    """Poll Langfuse API for traces matching session_id."""
    client = _get_api_client()
    for i in range(retries):
        result = client.trace.list(session_id=session_id, fields="core,io")
        if result.data and len(result.data) > 0:
            return result.data
        if i < retries - 1:
            time.sleep(delay)
    return []


def test_langfuse_multi_turn_global_chat():
    """2-turn conversation: vague request then clarification, with session_id."""
    print(f"\nLangfuse session_id: {SESSION_ID}")

    # --- Turn 1: vague request that should trigger clarification ---
    content_1 = "I need help with my integration"
    input_1 = {
        "content": content_1,
        "history": [],
        "meta": {
            "session_id": SESSION_ID,
            "user": {"id": USER_ID, "persona": "core-contributor"},
        },
        "metrics_opt_in": True,
    }

    response_1 = call_global_chat_service(input_1)
    print_response_details(response_1, test_name="turn_1", content=content_1)
    assert "response" in response_1, f"Turn 1 failed: {response_1}"
    history_1 = response_1.get("history", [
        {"role": "user", "content": content_1},
        {"role": "assistant", "content": response_1["response"]},
    ])

    # --- Turn 2: specific follow-up that should trigger planner ---
    content_2 = (
        "I want to create a workflow that fetches new patient registrations "
        "from CommCare every hour and creates matching tracked entities in DHIS2."
    )
    input_2 = {
        "content": content_2,
        "history": history_1,
        "meta": {
            "session_id": SESSION_ID,
            "user": {"id": USER_ID, "persona": "core-contributor"},
        },
        "metrics_opt_in": True,
    }

    response_2 = call_global_chat_service(input_2)
    print_response_details(response_2, test_name="turn_2", content=content_2)
    assert "response" in response_2, f"Turn 2 failed: {response_2}"

    # The planner should have generated a workflow
    yaml_str = get_attachment(response_2, "workflow_yaml")
    if yaml_str:
        parsed = yaml.safe_load(yaml_str)
        print(f"\nGenerated workflow has {len(parsed.get('jobs', {}))} jobs")

    # --- Verify traces in Langfuse ---
    traces = _fetch_traces(SESSION_ID)
    assert len(traces) >= 1, f"Expected traces for session {SESSION_ID}, found none"

    for trace in traces:
        # Verify user_id is set
        assert trace.user_id == USER_ID, f"Expected user_id={USER_ID}, got {trace.user_id}"
        # Verify tags include service name and persona
        assert "global_chat" in trace.tags, f"Missing 'global_chat' tag: {trace.tags}"
        assert "core-contributor" in trace.tags, f"Missing persona tag: {trace.tags}"
        # Verify api_key is NOT in trace input (capture_input=False fix)
        trace_input = str(trace.input or "")
        assert "api_key" not in trace_input, f"api_key leaked in trace input: {trace_input[:200]}"

    print(f"\n All 2 turns completed and verified in Langfuse for session: {SESSION_ID}")


def test_langfuse_global_chat_opt_out() -> None:
    """global_chat with metrics_opt_in absent should produce zero traces."""
    session = f"test-global-chat-optout-{uuid.uuid4().hex[:8]}"

    input_data = {
        "content": "What adaptors are available?",
        "history": [],
        "meta": {"session_id": session},
        # No metrics_opt_in — gate should drop this.
    }

    response = call_global_chat_service(input_data)
    assert "response" in response, f"Opt-out test failed: {response}"

    time.sleep(5)
    traces = _fetch_traces(session, retries=1, delay=0)
    assert len(traces) == 0, (
        f"Expected zero traces for opted-out session {session}, "
        f"found {len(traces)}. The should_export_span filter may not be working."
    )

    print(f"\n Opt-out verified (absent): zero traces for session: {session}")


def test_langfuse_global_chat_opt_out_explicit_false() -> None:
    """global_chat with metrics_opt_in=False should produce zero traces."""
    session = f"test-global-chat-optout-false-{uuid.uuid4().hex[:8]}"

    input_data = {
        "content": "What adaptors are available?",
        "history": [],
        "meta": {
            "session_id": session,
            "user": {"id": "test-user", "persona": "user"},
        },
        "metrics_opt_in": False,
    }

    response = call_global_chat_service(input_data)
    assert "response" in response, f"Opt-out (explicit false) test failed: {response}"

    time.sleep(5)
    traces = _fetch_traces(session, retries=1, delay=0)
    assert len(traces) == 0, (
        f"Expected zero traces for session {session} with metrics_opt_in=False, "
        f"found {len(traces)}."
    )

    print(f"\n Opt-out verified (explicit false): zero traces for session: {session}")
