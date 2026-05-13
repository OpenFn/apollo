"""User asks "are you there?" — the service should respond conversationally
about itself. It should use simple, user-facing language and not mention
internal data structures like YAML."""

from testing import judge
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import (
    assert_no_special_chars,
    assert_yaml_has_ids,
    assert_yaml_jobs_have_body,
)


QUALITY_CRITERIA = [
    "The response describes the service's capabilities in plain, user-facing language.",
    "The response does not expose internal implementation details such as YAML, schemas, or data formats.",
]


def test_simple_lang_bug(apollo_client):
    payload = build_workflow_chat_payload(
        existing_yaml="",
        history=[],
        user_message="are you there?",
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)

    response_text = response.get("response", "")
    assert "yaml" not in response_text.lower(), (
        f"Response should not mention 'YAML', but got: {response_text}"
    )

    if response.get("response_yaml"):
        assert_yaml_has_ids(response["response_yaml"])
        assert_yaml_jobs_have_body(response["response_yaml"])
        assert_no_special_chars(response["response_yaml"])

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
