"""
Langfuse tracing integration test for workflow_chat.

Runs 4 sequential conversation turns with the same session_id to verify
that Langfuse traces are created and grouped into a session.
Also tests that opting out produces zero traces.
"""
import os
import time
import uuid
from dotenv import load_dotenv
from langfuse.api import LangfuseAPI
from .test_utils import call_workflow_chat_service, make_service_input, print_response_details

load_dotenv()


SESSION_ID = f"test-workflow-chat-{uuid.uuid4().hex[:8]}"
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


def test_langfuse_multi_turn_workflow_chat():
    """4-turn conversation testing Langfuse trace grouping via session_id."""
    print(f"\nLangfuse session_id: {SESSION_ID}")

    # --- Turn 1: create a new workflow from scratch ---
    content_1 = "Create a workflow that receives patient data from a webhook, validates the required fields exist, and then sends the data to a DHIS2 instance."
    input_1 = make_service_input(
        existing_yaml="",
        history=[],
        content=content_1,
    )
    input_1["meta"] = {"session_id": SESSION_ID}
    input_1["user"] = {"id": USER_ID, "employee": True}
    input_1["metrics_opt_in"] = True

    response_1 = call_workflow_chat_service(input_1)
    print_response_details(response_1, content=content_1)
    assert "response" in response_1, f"Turn 1 failed: {response_1}"
    assert "response_yaml" in response_1, f"Turn 1 missing YAML: {response_1}"
    yaml_1 = response_1["response_yaml"]
    history_1 = response_1["history"]

    # --- Turn 2: modify the workflow ---
    content_2 = "Add a step between validation and DHIS2 that maps the patient fields to the DHIS2 tracked entity format."
    input_2 = make_service_input(
        existing_yaml=yaml_1,
        history=history_1,
        content=content_2,
    )
    input_2["meta"] = {"session_id": SESSION_ID}
    input_2["user"] = {"id": USER_ID, "employee": True}
    input_2["metrics_opt_in"] = True

    response_2 = call_workflow_chat_service(input_2)
    print_response_details(response_2, content=content_2)
    assert "response" in response_2, f"Turn 2 failed: {response_2}"
    assert "response_yaml" in response_2, f"Turn 2 missing YAML: {response_2}"
    yaml_2 = response_2["response_yaml"]
    history_2 = response_2["history"]

    # --- Turn 3: add error handling path ---
    content_3 = "If validation fails, instead of stopping the workflow, send the failed record to a Google Sheet for manual review."
    input_3 = make_service_input(
        existing_yaml=yaml_2,
        history=history_2,
        content=content_3,
    )
    input_3["meta"] = {"session_id": SESSION_ID}
    input_3["user"] = {"id": USER_ID, "employee": True}
    input_3["metrics_opt_in"] = True

    response_3 = call_workflow_chat_service(input_3)
    print_response_details(response_3, content=content_3)
    assert "response" in response_3, f"Turn 3 failed: {response_3}"
    assert "response_yaml" in response_3, f"Turn 3 missing YAML: {response_3}"
    yaml_3 = response_3["response_yaml"]
    history_3 = response_3["history"]

    # --- Turn 4: ask about the workflow ---
    content_4 = "Can you change the webhook trigger to a cron trigger that runs every 15 minutes?"
    input_4 = make_service_input(
        existing_yaml=yaml_3,
        history=history_3,
        content=content_4,
    )
    input_4["meta"] = {"session_id": SESSION_ID}
    input_4["user"] = {"id": USER_ID, "employee": True}
    input_4["metrics_opt_in"] = True

    response_4 = call_workflow_chat_service(input_4)
    print_response_details(response_4, content=content_4)
    assert "response" in response_4, f"Turn 4 failed: {response_4}"

    # --- Verify traces in Langfuse ---
    traces = _fetch_traces(SESSION_ID)
    assert len(traces) >= 1, f"Expected traces for session {SESSION_ID}, found none"

    for trace in traces:
        assert trace.user_id == USER_ID, f"Expected user_id={USER_ID}, got {trace.user_id}"
        assert "workflow_chat" in trace.tags, f"Missing 'workflow_chat' tag: {trace.tags}"
        assert "employee" in trace.tags, f"Missing 'employee' tag: {trace.tags}"
        trace_input = str(trace.input or "")
        assert "api_key" not in trace_input, f"api_key leaked in trace input: {trace_input[:200]}"

    print(f"\n All 4 turns completed and verified in Langfuse for session: {SESSION_ID}")


def test_langfuse_workflow_chat_opt_out():
    """workflow_chat with metrics_opt_in absent should produce zero traces."""
    opt_out_session = f"test-workflow-chat-optout-{uuid.uuid4().hex[:8]}"

    input_data = make_service_input(
        existing_yaml="",
        history=[],
        content="Create a simple webhook to HTTP workflow",
    )
    input_data["meta"] = {"session_id": opt_out_session}
    # No user, no metrics_opt_in

    response = call_workflow_chat_service(input_data)
    assert "response" in response, f"Opt-out test failed: {response}"

    # Wait briefly then confirm no traces were exported
    time.sleep(5)
    traces = _fetch_traces(opt_out_session, retries=1, delay=0)
    assert len(traces) == 0, (
        f"Expected zero traces for opted-out session {opt_out_session}, "
        f"found {len(traces)}. The should_export_span filter may not be working."
    )

    print(f"\n Opt-out verified (absent): zero traces for session: {opt_out_session}")


def test_langfuse_workflow_chat_opt_out_explicit_false():
    """workflow_chat with metrics_opt_in=False should produce zero traces."""
    session = f"test-workflow-chat-optout-false-{uuid.uuid4().hex[:8]}"

    input_data = make_service_input(
        existing_yaml="",
        history=[],
        content="Create a simple webhook to HTTP workflow",
    )
    input_data["meta"] = {"session_id": session}
    input_data["metrics_opt_in"] = False

    response = call_workflow_chat_service(input_data)
    assert "response" in response, f"Opt-out (explicit false) test failed: {response}"

    time.sleep(5)
    traces = _fetch_traces(session, retries=1, delay=0)
    assert len(traces) == 0, (
        f"Expected zero traces for session {session} with metrics_opt_in=False, "
        f"found {len(traces)}."
    )

    print(f"\n Opt-out verified (explicit false): zero traces for session: {session}")
