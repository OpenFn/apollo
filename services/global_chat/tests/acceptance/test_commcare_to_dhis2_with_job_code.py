"""From-scratch CommCare→DHIS2 workflow with job code for both steps. No
existing YAML, no history. The planner should be invoked, call the workflow
agent to produce a two-job workflow, then call the job code agent at least
twice to fill in the bodies."""

import yaml

from testing import judge
from testing.payloads import build_global_chat_payload
from testing.responses import assert_routed_to, assert_agent_calls, get_attachment
from testing.yaml_assertions import assert_yaml_has_ids, assert_yaml_jobs_have_body


QUALITY_CRITERIA = [
    "The response explains the workflow's purpose in plain language a non-engineer can follow.",
    "The job code for the CommCare step calls CommCare adaptor functions (e.g. submissions, forms, cases), not generic JavaScript.",
    "The job code for the DHIS2 step calls DHIS2 adaptor functions (e.g. create, upsert, trackedEntities), not generic JavaScript.",
    "The response does not leak an api_key or any value that looks like a secret.",
]


def test_commcare_to_dhis2_with_job_code(apollo_client):
    payload = build_global_chat_payload(
        user_message="Create a workflow that fetches patient cases from CommCare and registers them in DHIS2.",
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
    assert "jobs" in parsed, "YAML must have a jobs section"
    assert len(parsed["jobs"]) >= 2, f"Expected at least 2 jobs, got {len(parsed['jobs'])}"
    assert "triggers" in parsed, "YAML must have a triggers section"

    assert_yaml_has_ids(yaml_str)
    assert_yaml_jobs_have_body(yaml_str)

    assert_agent_calls(
        response.get("meta") or {},
        expected_agents=["planner", "workflow_agent", "job_agent"],
        min_job_code_calls=2,
    )

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(
        criteria=QUALITY_CRITERIA,
        candidate=response,
        test_notes=__doc__,
    )
    assert verdict.passed, verdict.summary
