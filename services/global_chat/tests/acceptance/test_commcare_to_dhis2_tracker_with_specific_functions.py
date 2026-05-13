"""User provides specific function-level instructions (each, fields, field,
tracker.import with strategy CREATE_AND_UPDATE, fn for logging). The planner
should pass that detail through to the job code agent and the generated code
should use those exact functions — not generic substitutes."""

from testing import judge
from testing.payloads import build_global_chat_payload


QUALITY_CRITERIA = [
    "The generated job code uses the specific functions the user named: each, fields, field, and tracker.import with strategy CREATE_AND_UPDATE.",
    "The generated job code includes a fn() step that logs the import summary (state.data.stats).",
    "The mapping correctly maps case_id to trackedEntity, owner_name to a DHIS2 attribute, and date_modified to enrollmentDate as specified.",
]


def test_commcare_to_dhis2_tracker_with_specific_functions(apollo_client):
    payload = build_global_chat_payload(
        user_message=(
            "Can you build a workflow that runs daily at 6am and syncs cases from "
            "CommCare to DHIS2 Tracker? It should have 4 steps: "
            "1. Fetch closed cases from CommCare from the last 24 hours. "
            "2. Use each() to iterate over the cases and use fields() and field() to "
            "map each case to a DHIS2 tracked entity instance — map case_id to "
            "trackedEntity, owner_name to a DHIS2 attribute, and date_modified to "
            "enrollmentDate. "
            "3. Import the mapped entities to DHIS2 using tracker.import() with "
            "strategy CREATE_AND_UPDATE and the async option set to false. "
            "4. Use fn() to log the import summary from state.data.stats to the console."
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
