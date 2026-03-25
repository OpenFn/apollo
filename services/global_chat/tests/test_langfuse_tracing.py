"""
Langfuse tracing integration test for global_chat.

Runs 2 sequential conversation turns with the same session_id:
  Turn 1: vague request that triggers clarification (no workflow generated)
  Turn 2: specific follow-up that triggers the planner to build a workflow

Check Langfuse UI after running to confirm trace hierarchy and session grouping.
"""
import uuid
import yaml
from .test_utils import call_global_chat_service, print_response_details, get_attachment


SESSION_ID = f"test-global-chat-{uuid.uuid4().hex[:8]}"


def test_langfuse_multi_turn_global_chat():
    """2-turn conversation: vague request then clarification, with session_id."""
    print(f"\nLangfuse session_id: {SESSION_ID}")

    # --- Turn 1: vague request that should trigger clarification ---
    content_1 = "I need help with my integration"
    input_1 = {
        "content": content_1,
        "history": [],
        "metadata": {"session_id": SESSION_ID},
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
        "metadata": {"session_id": SESSION_ID},
    }

    response_2 = call_global_chat_service(input_2)
    print_response_details(response_2, test_name="turn_2", content=content_2)
    assert "response" in response_2, f"Turn 2 failed: {response_2}"

    # The planner should have generated a workflow
    yaml_str = get_attachment(response_2, "workflow_yaml")
    if yaml_str:
        parsed = yaml.safe_load(yaml_str)
        print(f"\nGenerated workflow has {len(parsed.get('jobs', {}))} jobs")

    print(f"\n All 2 turns completed. Check Langfuse for session: {SESSION_ID}")
