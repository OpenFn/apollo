"""Basic input: a simple job-code modification request. The service should
return a response with both a text answer and a suggested_code patch when
suggest_code=True is set."""

from testing import judge
from testing.payloads import build_job_chat_payload


QUALITY_CRITERIA = []  # mostly structural; relies on universal rules + general flags


JOB_CODE = """// Get data from external API
get('https://api.example.com/data');

// Process and transform data
fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));

  return { ...state, transformed };
});

// Send transformed data to destination
post('https://destination.org/upload', state => state.transformed);"""


def test_basic_input(apollo_client):
    payload = build_job_chat_payload(
        user_message=(
            "Can you add error handling to this job that will log the error message "
            "and retry the operation once if the API call fails?"
        ),
        history=[],
        current_job_code=JOB_CODE,
        current_adaptor="@openfn/language-gmail@2.0.2",
        suggest_code=True,
    )

    response = apollo_client.call("job_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
