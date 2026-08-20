---
id: global-chat.gold.kobo-openmrs-verbose
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Verbose phrasing of the Kobo-to-OpenMRS patient registration pattern:
webhook-triggered submission, validate, dedup lookup, branch to
create-vs-update, plus an error path for invalid submissions. This is the
hardest cluster (branching, dedup, PII) and the user spells all of it out, so
the response should honor the explicit instructions. The ones that carry the
test:

- "Do not use the kobotoolbox adaptor to fetch anything, the data is already
  here" is explicit. The webhook delivers the submission in `state.data`; an
  added Kobo fetch step is a clear failure (the rubric's "no unnecessary extra
  steps").
- Validation must gate the writes: missing required fields (given name,
  family name, sex 'M'/'F', date of birth, national ID) fail the run so it
  routes to an error handler, and an invalid submission must never reach the
  OpenMRS write steps.
- Dedup and branching: look up by national ID, then create-vs-update as
  mutually exclusive paths. The update path touches demographics only and does
  not reassign identifiers, exactly as instructed.
- PII discipline is explicit here: log only the submission id, never names,
  dates of birth or national IDs, including in the error handler's message.

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: job names, adaptor versions,
exact openmrs function signatures, how the branch conditions are expressed
(edge conditions vs in-job logic), and how validation failure is routed may
all differ. Placeholder UUIDs for identifier type and location are expected
since the prompt says they are configured separately. Use it only to
sanity-check that the candidate is a plausible, coherent solution; we want to
catch clear issues against the explicit instructions above, not enforce this
exact structure.

```yaml
name: kobo-to-openmrs-registration
jobs:
  Validate-submission:
    name: Validate submission
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        const s = state.data;
        const required = ['given_name', 'family_name', 'sex', 'date_of_birth', 'national_id'];
        const missing = required.filter((f) => !s?.[f]);
        if (missing.length > 0 || !['M', 'F'].includes(s.sex)) {
          console.log(`Submission ${s?._id ?? '(no id)'} failed validation`);
          throw new Error('Invalid submission');
        }
        console.log(`Submission ${s._id} validated`);
        return { ...state, submission: s };
      });
  Lookup-patient:
    name: Look up patient by national ID
    adaptor: "@openfn/language-openmrs@latest"
    body: |
      get('patient', { q: $.submission.national_id });

      fn((state) => {
        const matches = state.data?.results ?? [];
        console.log(`Lookup returned ${matches.length} match(es)`);
        return { ...state, existingPatient: matches[0] ?? null };
      });
  Create-patient:
    name: Create patient
    adaptor: "@openfn/language-openmrs@latest"
    body: |
      create('patient', (state) => {
        const s = state.submission;
        return {
          identifiers: [
            {
              identifierType: state.identifierTypeUuid,
              identifier: s.national_id,
              location: state.locationUuid,
              preferred: true,
            },
          ],
          person: {
            names: [{ givenName: s.given_name, familyName: s.family_name }],
            gender: s.sex,
            birthdate: s.date_of_birth,
          },
        };
      });
  Update-patient:
    name: Update existing patient demographics
    adaptor: "@openfn/language-openmrs@latest"
    body: |
      update(`person/${$.existingPatient.uuid}`, (state) => {
        const s = state.submission;
        return {
          names: [{ givenName: s.given_name, familyName: s.family_name }],
          gender: s.sex,
          birthdate: s.date_of_birth,
        };
      });
  Log-invalid-submission:
    name: Log invalid submission
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log('Submission rejected by validation; no patient data written');
        return state;
      });
triggers:
  webhook:
    type: webhook
    enabled: true
edges:
  webhook->Validate-submission:
    condition_type: always
    enabled: true
    target_job: Validate-submission
    source_trigger: webhook
  Validate-submission->Lookup-patient:
    condition_type: on_job_success
    enabled: true
    target_job: Lookup-patient
    source_job: Validate-submission
  Validate-submission->Log-invalid-submission:
    condition_type: on_job_failure
    enabled: true
    target_job: Log-invalid-submission
    source_job: Validate-submission
  Lookup-patient->Create-patient:
    condition_type: js_expression
    condition_label: patient not found
    condition_expression: "!state.existingPatient"
    enabled: true
    target_job: Create-patient
    source_job: Lookup-patient
  Lookup-patient->Update-patient:
    condition_type: js_expression
    condition_label: patient exists
    condition_expression: "state.existingPatient"
    enabled: true
    target_job: Update-patient
    source_job: Lookup-patient
```

# quality_criteria

- The trigger is a webhook and there is no step that fetches data from KoboToolbox; the submission is consumed from `state.data` as the user explicitly instructed.
- A validation step checks the five required fields (given name, family name, sex as 'M' or 'F', date of birth, national ID) and fails the run when any are missing, so execution routes to an error handler rather than continuing.
- Invalid submissions never reach an OpenMRS write step: the create/update steps are only reachable after validation succeeds.
- A step looks the patient up in OpenMRS by national ID before any write.
- Create and update are mutually exclusive paths: create only runs when no match was found, update only when one was. On the create path the national ID is set as a preferred identifier alongside the demographics.
- The update path modifies demographics only and does not reassign or resend identifiers.
- Logging is PII-free everywhere, including the error handler: the submission id may be logged, but never names, dates of birth or national IDs.
- The openmrs adaptor is used for OpenMRS steps and common for validation/logging, with operations called with plausible arguments; identifier type and location UUIDs are placeholders or state/config references, and credentials are never hardcoded.

# turn

## role

user

## content

Build a workflow that registers patients in OpenMRS from a KoboToolbox registration form.
Trigger: a webhook. Kobo's REST Service posts one submission at a time as the request body, so the submission is already available in state.data. Do not use the kobotoolbox adaptor to fetch anything, the data is already here.
Steps:
Validate the submission. Required fields are given name, family name, sex ('M' or 'F'), date of birth, and national ID. If any are missing, fail the run so it routes to an error handler. Only log the submission id, never the personal fields.
Look up the patient in OpenMRS by national ID to check whether they already exist.
If they do not exist, create a new patient with their national ID as a preferred identifier plus their demographics.
If they already exist, update their demographics only. Do not reassign identifiers.
If validation failed, send the run to a separate step that logs a PII-free message.
Use the openmrs adaptor for the OpenMRS steps and common for validation and logging. Assume identifier type and location UUIDs are configured separately. Do not hardcode credentials. Do not log patient names, dates of birth, or national IDs anywhere.
