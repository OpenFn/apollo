import pytest
import yaml
from .test_utils import (
    call_global_agent_service,
    make_service_input,
    print_response_details,
    assert_routed_to,
    get_attachment,
    assert_yaml_has_ids,
)


def test_commcare_to_dhis2_with_job_code():
    print("==================TEST==================")
    print(
        "Description: From scratch - create a two-job CommCare→DHIS2 workflow and generate "
        "job code for both steps. No existing YAML, no history. Expects planner to orchestrate "
        "workflow_agent then job_code_agent."
    )
    content = (
        "Create a workflow that fetches patient cases from CommCare using "
        "@openfn/language-commcare@latest and registers them in DHIS2 using "
        "@openfn/language-dhis2@latest. Write the job code for both steps."
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

    # Planner should have made multiple tool calls
    meta = response.get("meta", {})
    assert "planner" in meta.get("agents", []), "Expected planner in agents list"
    assert meta.get("planner_iterations", 0) > 0, "Expected planner to make at least one tool call"


def test_http_to_salesforce_three_steps_with_job_code():
    print("==================TEST==================")
    print(
        "Description: From scratch - create a three-step HTTP→transform→Salesforce workflow "
        "and generate job code for all steps. No existing YAML, no history. Expects planner "
        "to orchestrate workflow_agent then multiple job_code_agent calls."
    )
    content = (
        "Build a complete OpenFn workflow from scratch with three steps: "
        "1) fetch records from an HTTP endpoint using @openfn/language-http@latest, "
        "2) transform the data using @openfn/language-common@latest, "
        "3) upsert contacts to Salesforce using @openfn/language-salesforce@latest. "
        "Generate the workflow YAML and job code for all three steps."
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

    # Planner should have made several tool calls (at minimum: 1 workflow + 1 code)
    meta = response.get("meta", {})
    assert "planner" in meta.get("agents", []), "Expected planner in agents list"
    assert meta.get("planner_iterations", 0) >= 2, (
        f"Expected at least 2 planner iterations (1 workflow + 1+ code), "
        f"got {meta.get('planner_iterations', 0)}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
