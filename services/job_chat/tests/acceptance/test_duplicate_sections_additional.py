"""Six identical POST calls. The user asks for retry-on-failure error handling
on the THIRD one only. The service must use enough context to identify the
right call, apply the change only there, and not accidentally drop any of
the other five."""

from testing import judge
from testing.payloads import build_job_chat_payload


QUALITY_CRITERIA = [
    "Error handling is added only to the third POST call — the others remain unchanged.",
    "All six POST calls are still present in the suggested code (none accidentally removed).",
]


JOB_CODE = """// Process and prepare data
fn(state => {
  const items = state.data.items.map(item => ({
    id: item.id,
    name: item.name,
    status: 'pending'
  }));

  return { ...state, items };
});

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);"""


def test_duplicate_sections_additional(apollo_client):
    payload = build_job_chat_payload(
        user_message="I need to add error handling only to the third POST request to retry once if it fails.",
        history=[],
        current_job_code=JOB_CODE,
        current_adaptor="@openfn/language-mailchimp@1.0.19",
        suggest_code=True,
    )

    response = apollo_client.call("job_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert response["suggested_code"] is not None
    assert response["suggested_code"] != JOB_CODE, "suggested_code should differ from the original"

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
