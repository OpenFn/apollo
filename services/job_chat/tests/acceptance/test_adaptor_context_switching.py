"""User was on a Salesforce job page and asked "How do I get data?"; the
assistant answered with SOQL. The user has now navigated to a DHIS2 job page
and asks the same question again. The model should notice the page-prefix
change and switch context to DHIS2-specific guidance."""

from testing import judge
from testing.payloads import build_job_chat_payload
from testing.responses import latest_user_message


QUALITY_CRITERIA = [
    "The response is specifically about fetching data from DHIS2 — not from Salesforce.",
    "The response references DHIS2 concepts (tracker, data values, events, programs, etc.) rather than SOQL or SQL.",
    "The response does not assume the previous Salesforce context still applies.",
]


def test_adaptor_context_switching(apollo_client):
    payload = build_job_chat_payload(
        user_message="How do I get data?",
        history=[
            {"role": "user", "content": "[pg:job_code/fetch-records/salesforce@9.0.3] How do I get data?"},
            {"role": "assistant", "content": (
                "To get data from Salesforce, you can use the `query()` operation with SOQL "
                "(Salesforce Object Query Language). For example:\n\n"
                "```js\nquery('SELECT Id, Name FROM Account WHERE Status = \"Active\"');\n```\n\n"
                "This will fetch records from Salesforce and store them in `state.data`."
            )},
        ],
        current_job_code="fn(state => {\n  return state;\n});",
        current_adaptor="@openfn/language-dhis2@8.0.7",
        current_page="fetch-data",
        suggest_code=False,
    )

    response = apollo_client.call("job_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert "response" in response

    # Page prefix was applied to the latest user turn in updated history
    latest_user = latest_user_message(response)
    assert latest_user is not None, "Expected at least one user message in updated history"
    assert "[pg:job_code/fetch-data/dhis2@8.0.7]" in latest_user["content"], (
        f"Expected DHIS2 page prefix in latest user message, got: {latest_user['content'][:200]}"
    )

    # DHIS2 mentioned in response text
    assert "dhis" in response["response"].lower(), (
        f"Expected DHIS2 to be mentioned in response. Got: {response['response'][:300]}"
    )

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(
        criteria=QUALITY_CRITERIA,
        candidate=response,
        test_notes=__doc__,
    )
    assert verdict.passed, verdict.summary
