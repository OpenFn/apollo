"""User was on a workflow editor discussing workflow structure, then navigated
to a job editor and asked an abrupt question about the current code. The model
should recognise the navigation (via meta.last_page) and respond about the
job code, not continue talking about workflow structure."""

from testing import judge
from testing.payloads import build_job_chat_payload


QUALITY_CRITERIA = [
    "The response is about the current job code (the patient mapping), not about workflow structure.",
]


JOB_CODE = """fn(state => {
  const patients = state.data.map(patient => ({
    id: patient.patient_id,
    name: patient.full_name,
    dob: patient.date_of_birth
  }));

  return { ...state, patients };
});

post('https://destination.api/patients', state => state.patients);"""


def test_navigation_workflow_to_job(apollo_client):
    payload = build_job_chat_payload(
        user_message="Add a log statement at the start",
        history=[
            {"role": "user", "content": "[pg:workflow/patient-sync] Create a workflow to sync patient data from source to destination"},
            {"role": "assistant", "content": "I'll create a workflow with jobs to fetch patient data, transform it, and sync to the destination system."},
            {"role": "user", "content": "[pg:workflow/patient-sync] Add validation between fetch and transform"},
            {"role": "assistant", "content": "I'll add a validation job that checks the patient data before transformation."},
        ],
        current_job_code=JOB_CODE,
        current_adaptor="@openfn/language-common@latest",
        current_page="map-patient-data",
        previous_page={"type": "workflow", "name": "patient-sync"},
        suggest_code=True,
    )

    response = apollo_client.call("job_chat", payload)

    # ---- Structural assertions ---------------------------------------------
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert response["suggested_code"] is not None, "Model should have generated code for the job"

    # Log statement was added
    assert "console.log" in response["suggested_code"], (
        f"Log statement not found in suggested code: {response['suggested_code'][:300]}"
    )

    # Response text is about job code, not workflow structure
    response_text = response["response"].lower()
    assert not any(word in response_text for word in ["workflow", "yaml", "trigger", "edge"]), (
        f"Response should be about job code, not workflow structure. Response: {response_text[:300]}"
    )

    # ---- Quality assertions ------------------------------------------------
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
