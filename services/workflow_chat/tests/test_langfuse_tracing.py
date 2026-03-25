"""
Langfuse tracing integration test for workflow_chat.

Runs 4 sequential conversation turns with the same session_id to verify
that Langfuse traces are created and grouped into a session.
Check Langfuse UI after running to confirm trace hierarchy.
"""
import uuid
from .test_utils import call_workflow_chat_service, make_service_input, print_response_details


SESSION_ID = f"test-workflow-chat-{uuid.uuid4().hex[:8]}"


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

    response_4 = call_workflow_chat_service(input_4)
    print_response_details(response_4, content=content_4)
    assert "response" in response_4, f"Turn 4 failed: {response_4}"

    print(f"\n All 4 turns completed. Check Langfuse for session: {SESSION_ID}")
