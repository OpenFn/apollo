"""From-scratch three-step HTTP→transform→Salesforce workflow with job code
for all three steps. The planner should call the workflow agent to produce a
three-job workflow, then call the job code agent at least three times to fill
in the bodies."""

import yaml

from testing import judge
from testing.payloads import build_global_chat_payload
from testing.responses import assert_routed_to, assert_agent_calls, get_attachment
from testing.yaml_assertions import assert_yaml_has_ids, assert_yaml_jobs_have_body


QUALITY_CRITERIA = [
    "Each job's body uses functions appropriate to its adaptor (HTTP get/post for the fetch step, JS for transform, Salesforce upsert for the destination).",
]


def test_http_to_salesforce_three_steps_with_job_code(apollo_client):
    payload = build_global_chat_payload(
        user_message=(
            "Build a workflow that can fetch records from an HTTP endpoint, "
            "transform the data, and upsert contacts to Salesforce."
        ),
        history=[],
    )

    response = apollo_client.call("global_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    assert_routed_to(response, "planner")

    yaml_str = get_attachment(response, "workflow_yaml")
    assert yaml_str, "Expected a workflow_yaml attachment"

    parsed = yaml.safe_load(yaml_str)
    assert "jobs" in parsed
    assert len(parsed["jobs"]) >= 3, f"Expected at least 3 jobs, got {len(parsed['jobs'])}"
    assert_yaml_has_ids(yaml_str)
    assert_yaml_jobs_have_body(yaml_str)

    assert_agent_calls(
        response.get("meta") or {},
        expected_agents=["planner", "workflow_agent", "job_agent"],
        min_job_code_calls=3,
    )

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
