"""
Langfuse tracing integration test for job_chat.

Runs 4 sequential conversation turns with the same session_id to verify
that Langfuse traces are created and grouped into a session.
Check Langfuse UI after running to confirm trace hierarchy.
"""
import uuid
from .test_utils import call_job_chat_service, make_service_input, print_response_details


SESSION_ID = f"test-job-chat-{uuid.uuid4().hex[:8]}"

CONTEXT = {
    "expression": """// Fetch patient data from FHIR server
get('Patient', { count: 100 });

fn(state => {
  const patients = state.data.entry.map(e => e.resource);
  return { ...state, patients };
});""",
    "adaptor": "@openfn/language-http@6.5.1",
}


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

    response_4 = call_job_chat_service(input_4)
    print_response_details(response_4, test_name="turn_4", content=content_4)
    assert "response" in response_4, f"Turn 4 failed: {response_4}"

    print(f"\n✅ All 4 turns completed. Check Langfuse for session: {SESSION_ID}")
