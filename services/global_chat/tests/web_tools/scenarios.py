"""The six web-tools scenarios, shared by the runner and the pass/fail suite.

Each scenario has a trap: a reason the model might use the web wrongly.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    turns: tuple[str, ...]
    workflow_yaml: str | None = None
    page: str | None = None
    # Ground truth, each string must be in the answer and in a fetched page.
    facts: tuple[str, ...] = ()
    # The control must make no web calls.
    control: bool = False
    source_page: str | None = None


FHIR_MAPPING_YAML = """\
name: commcare-to-fhir
jobs:
  map-patient:
    id: job-map-patient
    name: Map Patient
    adaptor: "@openfn/language-common@latest"
    body: |
      fn(state => {
        const patient = {
          resourceType: 'Patient',
          firstName: state.data.first_name,
          lastName: state.data.last_name,
          gender: state.data.sex,
        };
        return { ...state, patient };
      });
triggers:
  webhook:
    id: trigger-webhook
    type: webhook
    enabled: true
edges:
  webhook->map-patient:
    id: edge-webhook-map
    source_trigger: webhook
    target_job: map-patient
    condition_type: always
    enabled: true
"""

SCENARIOS = {s.id: s for s in (
    # docs.openfn.org is allowlisted, which tempts a fetch; search_documentation is the right tool.
    Scenario(
        id="control_openfn_concept",
        turns=("What does each() do in OpenFn job code, and when should I use it instead of fn()?",),
        control=True,
    ),
    # FHIR vocabulary is found everywhere, but this is a pure JavaScript edit.
    Scenario(
        id="control_code_edit",
        turns=("In this step, rename the firstName field to given and wrap its value in an array.",),
        workflow_yaml=FHIR_MAPPING_YAML,
        page="workflows/commcare-to-fhir/map-patient",
        control=True,
    ),
    # Positive case: the fact is inside what a 10k fetch returns.
    # Calibrated, where the pat-1 constraint text sits at char ~24.5k of the ~26k a 10k fetch returns.
    Scenario(
        id="fhir_shallow",
        turns=("In FHIR R4, what rule applies to each entry in Patient.contact? What must it contain at minimum?",),
        facts=("contact's details", "reference to an organization"),
    ),
    # Calibrated: absent from a 10k fetch of patient.html, present from 25k (char ~34.9k).
    # The codes also sit near the top of the short valueset-link-type.html page, so a
    # grounded answer does not by itself show truncation was avoided.
    Scenario(
        id="fhir_deep",
        turns=("In FHIR R4, what codes can Patient.link.type take, and what does each mean?",),
        facts=("replaced-by", "seealso"),
        source_page="hl7.org/fhir/R4/patient.html",
    ),
    # The model knows docs.dhis2.org from training, but it is not on the allowlist.
    Scenario(
        id="off_allowlist",
        turns=("What fields does the DHIS2 tracker API (/api/tracker) accept when creating an event?",),
    ),
    # Turn 2 is answerable from turn 1's page, and turn 3 barely needs it.
    Scenario(
        id="multi_turn",
        turns=(
            "Which fields does a FHIR R4 Patient have for contact information?",
            "Which of those fields can repeat?",
            "How would I map a CommCare phone number into it?",
        ),
    ),
)}
