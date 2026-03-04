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


def test_good_morning_email_workflow():
    print("==================TEST==================")
    print(
        "Description: From scratch - create a scheduled Gmail workflow that sends a good morning "
        "email every day at 9am. No existing YAML, no history. Expects the planner to orchestrate "
        "workflow_agent (cron trigger + Gmail job) then job_code_agent (Gmail send email code)."
    )

    content = (
        "Create a workflow that starts my day on a good note. "
        "Every day at 9am send myself a good morning email (x@openfn.org) via gmail."
    )
    service_input = make_service_input(content=content, history=[])
    response = call_global_agent_service(service_input)
    print_response_details(response, test_name="test_good_morning_email_workflow", content=content)

    assert response is not None
    assert isinstance(response, dict)

    # Should be routed to planner (needs both workflow structure AND job code)
    assert_routed_to(response, "planner", context="test_good_morning_email_workflow")

    # --- Workflow YAML checks ---
    yaml_str = get_attachment(response, "workflow_yaml")
    assert yaml_str is not None, "Expected a workflow_yaml attachment"

    parsed = yaml.safe_load(yaml_str)

    # Should have a jobs section with at least one job (send email)
    assert "jobs" in parsed, "YAML must have a jobs section"
    assert len(parsed["jobs"]) >= 1, f"Expected at least 1 job, got {len(parsed['jobs'])}"

    # Should have a cron trigger set to 9am
    assert "triggers" in parsed, "YAML must have a triggers section"
    triggers = parsed["triggers"]
    cron_triggers = [t for t in triggers.values() if t.get("type") == "cron"]
    assert len(cron_triggers) >= 1, "Expected at least one cron trigger"

    cron_values = [t.get("cron_expression", "") for t in cron_triggers]
    assert any("9" in c or "09" in c for c in cron_values), (
        f"Expected a 9am cron expression, got: {cron_values}"
    )

    # Should reference the Gmail adaptor somewhere in jobs
    jobs_yaml = yaml_str.lower()
    assert "gmail" in jobs_yaml, "Expected Gmail adaptor to be referenced in the workflow YAML"

    # All jobs and triggers should have valid IDs
    assert_yaml_has_ids(yaml_str, context="test_good_morning_email_workflow")

    # All jobs should have a non-empty body
    assert_yaml_jobs_have_body(yaml_str, context="test_good_morning_email_workflow")

    # --- Planner meta checks ---
    meta = response.get("meta", {})
    assert "planner" in meta.get("agents", []), "Expected planner in agents list"
    assert meta.get("planner_iterations", 0) >= 2, (
        f"Expected at least 2 planner iterations (1 workflow + 1 job code), "
        f"got {meta.get('planner_iterations', 0)}"
    )

    # workflow_agent should have been called to build the workflow structure
    agents = meta.get("agents", [])
    assert "workflow_agent" in agents, "Expected workflow_agent to have been called"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
