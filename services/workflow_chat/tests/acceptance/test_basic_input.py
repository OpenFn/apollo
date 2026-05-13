"""Basic input: empty yaml, simple request. The service should either generate
a YAML or ask for more information. Structural checks ensure any generated YAML
is well-formed."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import (
    assert_no_special_chars,
    assert_yaml_has_ids,
    assert_yaml_jobs_have_body,
)


QUALITY_CRITERIA = []  # mostly structural; relies on universal rules + general flags


def test_basic_input(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml="",
        history=[],
        user_message=(
            "Whenever fridge statistics are send to you, parse and aggregate "
            "the data and upload to a collection in redis."
        ),
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)

    if response.get("response_yaml"):
        assert_yaml_has_ids(response["response_yaml"])
        assert_yaml_jobs_have_body(response["response_yaml"])
        assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
