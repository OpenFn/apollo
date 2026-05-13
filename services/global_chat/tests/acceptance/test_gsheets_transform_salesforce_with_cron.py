"""Semi-specific request: cron trigger at midnight, fetch from Google Sheets,
transform, upsert to Salesforce. The Salesforce upsert step requires field
mapping decisions the user hasn't provided. The planner should acknowledge
the missing details rather than inventing field mappings silently."""

from testing import judge
from testing.payloads import build_global_chat_payload


QUALITY_CRITERIA = [
    "The response acknowledges that the Salesforce upsert needs field-mapping details from the user (object type, key fields, source-to-target mapping).",
    "If the response generates job code or YAML, it does not silently fabricate field mappings the user did not provide.",
]


def test_gsheets_transform_salesforce_with_cron(apollo_client):
    payload = build_global_chat_payload(
        user_message=(
            "Can you make a workflow that triggers at midnight, fetches data from "
            "Google Sheets, transforms it, and upserts it into Salesforce?"
        ),
        history=[],
    )

    response = apollo_client.call("global_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    assert "response" in response
    assert len(response["response"]) > 0

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
