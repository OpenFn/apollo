---
id: global-chat.gold.kobo-openmrs-vague
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Vague phrasing of the Kobo-to-OpenMRS patient registration pattern:
webhook-triggered form submission, dedup lookup, then create or update in
OpenMRS. The user gives only two hard requirements, so those two carry the
test:

- "When a new Kobo form is submitted" pins an event-driven shape: a webhook
  trigger that runs once per submission (Kobo's REST Service posts each
  submission). A cron job that polls in batches does not match "when a form is
  submitted".
- "Don't create duplicates" is the heart of the task: the workflow must look
  the patient up in OpenMRS before writing, and only create when no match is
  found. On a match it should update or skip, not blindly create. The two
  outcomes must be mutually exclusive, whether that is expressed as branch
  edges or as in-job conditional logic.

Beyond that, the phrasing is loose, so keep evaluation loose. The broader
rubric this task comes from also covers field validation, PII-free logging,
and "no match / multiple match" edge cases; the user asked for none of that
here, so treat it as a bonus if present and do not penalize its absence. The
form fields and OpenMRS identifier/location UUIDs are unknown, so sensible
assumptions and clearly named placeholders are expected and fine. Hardcoded
credentials would still be a clear issue (credentials belong in the adaptor
configuration).

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: step count, job names,
adaptor versions, the exact openmrs function signatures, the assumed form
field names, and whether create-vs-update is done via branch edges or inside
one job body may all differ. A validation step or an error path is also fine
even though this reference has none. Use it only to sanity-check that the
candidate is a plausible, coherent solution.

```yaml
name: kobo-to-openmrs-registration
jobs:
  Prepare-submission:
    name: Prepare submission
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log(`Processing submission ${state.data?._id ?? '(no id)'}`);
        return { ...state, submission: state.data };
      });
  Lookup-patient:
    name: Look up patient in OpenMRS
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
    name: Update existing patient
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
triggers:
  webhook:
    type: webhook
    enabled: true
edges:
  webhook->Prepare-submission:
    condition_type: always
    enabled: true
    target_job: Prepare-submission
    source_trigger: webhook
  Prepare-submission->Lookup-patient:
    condition_type: on_job_success
    enabled: true
    target_job: Lookup-patient
    source_job: Prepare-submission
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

- A complete workflow is produced (assumptions and placeholder UUIDs or field names are fine), rather than only clarifying questions.
- The trigger is a webhook so the workflow runs per Kobo submission, not a cron poll.
- Before any write, a step looks the patient up in OpenMRS by some identifying field to check whether they already exist.
- A patient is created only when the lookup found no match; when a match exists the workflow updates or skips instead. Exactly one of these outcomes applies per submission, whether via mutually exclusive branch edges or conditional logic inside a job.
- The OpenMRS steps use the openmrs adaptor with real functions and plausible arguments, not invented ones, and each step returns state.
- Credentials are left to the adaptor configuration, never hardcoded in job code.
- Do not require validation steps, error handlers or PII-safe logging; the user did not ask for them in this phrasing (they are fine to include).

# turn

## role

user

## content

When a new Kobo form is submitted, register the patient in OpenMRS. Don't create duplicates.
