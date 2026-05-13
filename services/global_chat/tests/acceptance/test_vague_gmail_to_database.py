"""Vague request: "fetch my data from gmail and send it to my database". No
specifics on which gmail data, which database, how to map between them. The
planner should surface the ambiguity (or ask clarifying questions) rather
than silently inventing details."""

from testing import judge
from testing.payloads import build_global_chat_payload


QUALITY_CRITERIA = [
    "The response surfaces the ambiguities in the user's request (e.g. which gmail data, which database, how to authenticate) rather than silently inventing unstated requirements.",
    "If the response asks clarifying questions, they are concrete and answerable, not generic.",
]


def test_vague_gmail_to_database(apollo_client):
    payload = build_global_chat_payload(
        user_message="I want to fetch my data from gmail and send it to my database",
        history=[],
    )

    response = apollo_client.call("global_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert isinstance(response, dict)
    assert "response" in response, "Expected a text response"
    assert len(response["response"]) > 0, "Expected non-empty response"

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
