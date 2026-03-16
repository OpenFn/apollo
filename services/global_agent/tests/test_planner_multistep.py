import pytest
import yaml
from .test_utils import (
    call_global_agent_service,
    make_service_input,
    print_response_details,
    assert_routed_to,
    get_attachment,
    assert_yaml_has_ids,
    assert_yaml_jobs_have_body,
)


def assert_agent_calls(meta, expected_agents, min_job_code_calls, context=""):
    """
    Assert that the planner called the expected sub-agents in the correct order.

    Checks:
    - workflow_agent and job_code_agent appear in meta["agents"]
    - tool_calls show workflow_agent before any job_code_agent calls
    - job_code_agent was called at least min_job_code_calls times
    """
    agents = meta.get("agents", [])
    for agent in expected_agents:
        assert agent in agents, (
            f"{context}: Expected '{agent}' in agents list, got {agents}"
        )

    tool_calls = meta.get("tool_calls", [])
    tool_names = [tc["tool"] for tc in tool_calls]

    # workflow_agent must be called
    assert "call_workflow_agent" in tool_names, (
        f"{context}: Expected call_workflow_agent in tool_calls, got {tool_names}"
    )

    # job_code_agent must be called enough times
    job_code_indices = [i for i, t in enumerate(tool_names) if t == "call_job_code_agent"]
    assert len(job_code_indices) >= min_job_code_calls, (
        f"{context}: Expected at least {min_job_code_calls} call_job_code_agent calls, "
        f"got {len(job_code_indices)}. Tool calls: {tool_names}"
    )

    # workflow_agent must come before all job_code_agent calls
    workflow_idx = tool_names.index("call_workflow_agent")
    for j in job_code_indices:
        assert j > workflow_idx, (
            f"{context}: call_job_code_agent at index {j} came before "
            f"call_workflow_agent at index {workflow_idx}. Tool calls: {tool_names}"
        )


def test_commcare_to_dhis2_with_job_code():
    print("==================TEST==================")
    print(
        "Description: From scratch - create a two-job CommCare→DHIS2 workflow and generate "
        "job code for both steps. No existing YAML, no history. Expects planner to orchestrate "
        "workflow_agent then job_code_agent."
    )
    content = (
        "Create a workflow that fetches patient cases from CommCare and registers them in DHIS2."
    )
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_commcare_to_dhis2_with_job_code", content=content)

    assert response is not None
    assert isinstance(response, dict)
    assert_routed_to(response, "planner", context="test_commcare_to_dhis2_with_job_code")

    # Should return a workflow YAML attachment
    yaml_str = get_attachment(response, "workflow_yaml")
    assert yaml_str is not None, "Expected a workflow_yaml attachment"

    parsed = yaml.safe_load(yaml_str)
    assert "jobs" in parsed, "YAML must have a jobs section"
    assert len(parsed["jobs"]) >= 2, f"Expected at least 2 jobs, got {len(parsed['jobs'])}"
    assert "triggers" in parsed, "YAML must have a triggers section"
    assert_yaml_has_ids(yaml_str, context="test_commcare_to_dhis2_with_job_code")

    # Verify correct agents called in correct order: planner -> workflow_agent -> job_code_agent x2
    meta = response.get("meta", {})
    assert_agent_calls(
        meta,
        expected_agents=["planner", "workflow_agent", "job_agent"],
        min_job_code_calls=2,
        context="test_commcare_to_dhis2_with_job_code",
    )

    # Every job must have a non-empty body
    assert_yaml_jobs_have_body(yaml_str, context="test_commcare_to_dhis2_with_job_code")


def test_http_to_salesforce_three_steps_with_job_code():
    print("==================TEST==================")
    print(
        "Description: From scratch - create a three-step HTTP→transform→Salesforce workflow "
        "and generate job code for all steps. No existing YAML, no history. Expects planner "
        "to orchestrate workflow_agent then multiple job_code_agent calls."
    )
    content = (
        "Build a workflow that can fetch records from an HTTP endpoint, "
        "transform the data, and upsert contacts to Salesforce."
    )
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_http_to_salesforce_three_steps_with_job_code", content=content)

    assert response is not None
    assert isinstance(response, dict)
    assert_routed_to(response, "planner", context="test_http_to_salesforce_three_steps_with_job_code")

    # Should return a workflow YAML attachment
    yaml_str = get_attachment(response, "workflow_yaml")
    assert yaml_str is not None, "Expected a workflow_yaml attachment"

    parsed = yaml.safe_load(yaml_str)
    assert "jobs" in parsed, "YAML must have a jobs section"
    assert len(parsed["jobs"]) >= 3, f"Expected at least 3 jobs, got {len(parsed['jobs'])}"
    assert_yaml_has_ids(yaml_str, context="test_http_to_salesforce_three_steps_with_job_code")

    # Verify correct agents called in correct order: planner -> workflow_agent -> job_code_agent x3
    meta = response.get("meta", {})
    assert_agent_calls(
        meta,
        expected_agents=["planner", "workflow_agent", "job_agent"],
        min_job_code_calls=3,
        context="test_http_to_salesforce_three_steps_with_job_code",
    )

    # Every job must have a non-empty body
    assert_yaml_jobs_have_body(yaml_str, context="test_http_to_salesforce_three_steps_with_job_code")


def test_vague_gmail_to_database():
    """Vague request with no adaptors or structure specified - see how planner handles ambiguity."""
    print("==================TEST==================")
    print(
        "Description: Vague request - 'fetch data from gmail and send to database'. "
        "Not enough info to fully construct a workflow. Exploring planner behavior."
    )
    content = "I want to fetch my data from gmail and send it to my database"
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_vague_gmail_to_database", content=content)

    assert response is not None
    assert isinstance(response, dict)
    assert "response" in response, "Expected a text response"
    assert len(response["response"]) > 0, "Expected non-empty response"

    meta = response.get("meta", {})
    print(f"\n  Agents used: {meta.get('agents', [])}")
    print(f"  Tool calls: {[tc['tool'] for tc in meta.get('tool_calls', [])]}")


def test_gsheets_transform_salesforce_with_cron():
    """More specific request with cron trigger, but still underspecified transform/upsert steps.
    Using Salesforce as destination to imply specific field mapping requirements the user hasn't specified."""
    print("==================TEST==================")
    print(
        "Description: Semi-specific request - cron trigger, google sheets, transform, salesforce upsert. "
        "Salesforce upsert implies field mapping decisions the user hasn't specified. Exploring planner behavior."
    )
    content = (
        "Can you make a workflow that triggers at midnight, fetches data from "
        "Google Sheets, transforms it, and upserts it into Salesforce?"
    )
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_gsheets_transform_salesforce_with_cron", content=content)

    assert response is not None
    assert isinstance(response, dict)
    assert "response" in response, "Expected a text response"
    assert len(response["response"]) > 0, "Expected non-empty response"

    meta = response.get("meta", {})
    print(f"\n  Agents used: {meta.get('agents', [])}")
    print(f"  Tool calls: {[tc['tool'] for tc in meta.get('tool_calls', [])]}")


def test_commcare_to_dhis2_tracker_with_specific_functions():
    """User provides specific function details - tests whether planner passes them faithfully to job code agent."""
    print("==================TEST==================")
    print(
        "Description: User specifies exact DHIS2 tracker functions and common adaptor helpers. "
        "Tests whether the planner passes function-level detail through to job code agent."
    )
    content = (
        "Can you build a workflow that runs daily at 6am and syncs cases from CommCare to DHIS2 Tracker? "
        "It should have 4 steps: "
        "1. Fetch closed cases from CommCare from the last 24 hours. "
        "2. Use each() to iterate over the cases and use fields() and field() to map each case "
        "to a DHIS2 tracked entity instance — map case_id to trackedEntity, owner_name to a DHIS2 attribute, "
        "and date_modified to enrollmentDate. "
        "3. Import the mapped entities to DHIS2 using tracker.import() with strategy CREATE_AND_UPDATE "
        "and the async option set to false. "
        "4. Use fn() to log the import summary from state.data.stats to the console."
    )
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_commcare_to_dhis2_tracker_with_specific_functions", content=content)

    assert response is not None
    assert isinstance(response, dict)
    assert "response" in response, "Expected a text response"
    assert len(response["response"]) > 0, "Expected non-empty response"

    meta = response.get("meta", {})
    print(f"\n  Agents used: {meta.get('agents', [])}")
    print(f"  Tool calls: {[tc['tool'] for tc in meta.get('tool_calls', [])]}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
