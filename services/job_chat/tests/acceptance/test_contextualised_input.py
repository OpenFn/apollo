"""All payload fields populated: history, job code, multiple adaptors, ids,
and pre-injected RAG search results in meta. The service should pick up on
the RAG hints (HTTP adaptor error handling, retry logic) and produce a
suggested_code that differs from the original."""

from testing import judge
from testing.payloads import build_job_chat_payload


QUALITY_CRITERIA = [
    "The response or suggested_code references the pre-injected RAG search results (HTTP adaptor error handling and retry logic) rather than ignoring them.",
]


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


def test_contextualised_input(apollo_client):
    payload = build_job_chat_payload(
        user_message=(
            "Can you add error handling to this job that will log the error message "
            "and retry the operation once if the API call fails?"
        ),
        history=[
            {
                "role": "user",
                "content": "I need to add error handling to my API integration job. What's the best approach?",
            },
            {
                "role": "assistant",
                "content": (
                    "There are several approaches to handling errors in API calls. You can use "
                    "try/catch blocks, implement retry logic, or use built-in error handling "
                    "functions. Could you share your current job code so I can provide specific "
                    "recommendations?"
                ),
            },
        ],
        current_job_code=JOB_CODE,
        current_adaptor="@openfn/language-fhir-4@0.1.10",
        project_adaptors=["@openfn/language-http", "@openfn/language-common"],
        job_id="job-abc123",
        project_id="project-xyz789",
        rag_results=[
            {
                "title": "HTTP Adaptor Error Handling",
                "url": "https://docs.openfn.org/adaptors/http#error-handling",
                "content": (
                    "The HTTP adaptor provides mechanisms for handling connection errors and "
                    "retrying failed requests. Use the maxRetries option to specify retry attempts."
                ),
            },
            {
                "title": "Common Adaptor Documentation",
                "url": "https://docs.openfn.org/adaptors/common#error-handling",
                "content": (
                    "Error handling can be implemented using standard JavaScript try/catch "
                    "blocks or with the withError helper function."
                ),
            },
        ],
        rag_queries=["http adaptor error handling", "openfn retry logic"],
        suggest_code=True,
    )

    response = apollo_client.call("job_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert "meta" in response
    assert "usage" in response
    assert response["suggested_code"] is not None, "suggested_code should not be None"
    assert response["suggested_code"] != JOB_CODE, "suggested_code should differ from the original"

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
