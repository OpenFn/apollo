"""
Langfuse tracing integration test for job_chat.

Runs 4 sequential conversation turns with the same session_id to verify
that Langfuse traces are created and grouped into a session.
Also tests that opting out produces zero traces.
"""
import os
import time
import uuid
from dotenv import load_dotenv
from langfuse.api import LangfuseAPI
from .test_utils import call_job_chat_service, make_service_input, print_response_details

load_dotenv()


SESSION_ID = f"test-job-chat-{uuid.uuid4().hex[:8]}"
USER_ID = f"test-user-{uuid.uuid4().hex[:8]}"

CONTEXT = {
    "expression": """// Fetch patient data from FHIR server
get('Patient', { count: 100 });

fn(state => {
  const patients = state.data.entry.map(e => e.resource);
  return { ...state, patients };
});""",
    "adaptor": "@openfn/language-http@6.5.1",
}


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


def test_langfuse_multi_turn_job_chat():
    """4-turn conversation testing Langfuse trace grouping via session_id."""
    print(f"\nLangfuse session_id: {SESSION_ID}")

    # --- Turn 1: initial question ---
    content_1 = "Can you add error handling so that if the GET request fails it logs the error and returns an empty array?"
    input_1 = make_service_input(
        history=[],
        content=content_1,
        context=CONTEXT,
        suggest_code=True,
    )
    input_1["meta"] = {"session_id": SESSION_ID}
    input_1["user"] = {"id": USER_ID, "employee": True}
    input_1["metrics_opt_in"] = True

    response_1 = call_job_chat_service(input_1)
    print_response_details(response_1, test_name="turn_1", content=content_1)
    assert "response" in response_1, f"Turn 1 failed: {response_1}"
    history_1 = response_1["history"]

    # --- Turn 2: follow-up refinement ---
    content_2 = "Good, but can you also add a retry with a 2 second delay before giving up?"
    input_2 = make_service_input(
        history=history_1,
        content=content_2,
        context={
            **CONTEXT,
            "expression": response_1.get("suggested_code") or CONTEXT["expression"],
        },
        meta={"rag": response_1.get("meta", {}).get("rag")},
        suggest_code=True,
    )
    input_2["meta"]["session_id"] = SESSION_ID
    input_2["user"] = {"id": USER_ID, "employee": True}
    input_2["metrics_opt_in"] = True

    response_2 = call_job_chat_service(input_2)
    print_response_details(response_2, test_name="turn_2", content=content_2)
    assert "response" in response_2, f"Turn 2 failed: {response_2}"
    history_2 = response_2["history"]

    # --- Turn 3: ask a question (no code suggestion) ---
    content_3 = "What HTTP status codes would cause the retry to trigger?"
    input_3 = make_service_input(
        history=history_2,
        content=content_3,
        context={
            **CONTEXT,
            "expression": response_2.get("suggested_code") or CONTEXT["expression"],
        },
        meta={"rag": response_2.get("meta", {}).get("rag")},
        suggest_code=False,
    )
    input_3["meta"]["session_id"] = SESSION_ID
    input_3["user"] = {"id": USER_ID, "employee": True}
    input_3["metrics_opt_in"] = True

    response_3 = call_job_chat_service(input_3)
    print_response_details(response_3, test_name="turn_3", content=content_3)
    assert "response" in response_3, f"Turn 3 failed: {response_3}"
    history_3 = response_3["history"]

    # --- Turn 4: back to code changes ---
    content_4 = "Ok, let's only retry on 429 and 503 status codes. Update the code."
    input_4 = make_service_input(
        history=history_3,
        content=content_4,
        context={
            **CONTEXT,
            "expression": response_2.get("suggested_code") or CONTEXT["expression"],
        },
        meta={"rag": response_3.get("meta", {}).get("rag") if "meta" in response_3 else None},
        suggest_code=True,
    )
    input_4["meta"]["session_id"] = SESSION_ID
    input_4["user"] = {"id": USER_ID, "employee": True}
    input_4["metrics_opt_in"] = True

    response_4 = call_job_chat_service(input_4)
    print_response_details(response_4, test_name="turn_4", content=content_4)
    assert "response" in response_4, f"Turn 4 failed: {response_4}"

    # --- Verify traces in Langfuse ---
    traces = _fetch_traces(SESSION_ID)
    assert len(traces) >= 1, f"Expected traces for session {SESSION_ID}, found none"

    for trace in traces:
        assert trace.user_id == USER_ID, f"Expected user_id={USER_ID}, got {trace.user_id}"
        assert "job_chat" in trace.tags, f"Missing 'job_chat' tag: {trace.tags}"
        assert "employee" in trace.tags, f"Missing 'employee' tag: {trace.tags}"
        trace_input = str(trace.input or "")
        assert "api_key" not in trace_input, f"api_key leaked in trace input: {trace_input[:200]}"

    print(f"\n All 4 turns completed and verified in Langfuse for session: {SESSION_ID}")


def test_langfuse_job_chat_opt_out():
    """job_chat with metrics_opt_in absent should produce zero traces."""
    opt_out_session = f"test-job-chat-optout-{uuid.uuid4().hex[:8]}"

    input_data = make_service_input(
        history=[],
        content="How do I use the HTTP adaptor?",
        context=CONTEXT,
        suggest_code=False,
    )
    input_data["meta"] = {"session_id": opt_out_session}
    # No user, no metrics_opt_in

    response = call_job_chat_service(input_data)
    assert "response" in response, f"Opt-out test failed: {response}"

    # Wait briefly then confirm no traces were exported
    time.sleep(5)
    traces = _fetch_traces(opt_out_session, retries=1, delay=0)
    assert len(traces) == 0, (
        f"Expected zero traces for opted-out session {opt_out_session}, "
        f"found {len(traces)}. The should_export_span filter may not be working."
    )

    print(f"\n Opt-out verified: zero traces for session: {opt_out_session}")
