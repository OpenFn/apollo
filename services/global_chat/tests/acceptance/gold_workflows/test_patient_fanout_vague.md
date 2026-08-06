---
id: global-chat.gold.patient-fanout-vague
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Vague phrasing of the large fan-out pattern: a webhook-delivered patient form
goes to OpenMRS (deduplicated), then on to DHIS2 and a FHIR server. The user
gives one sentence, so the test is about whether the assistant gets the
skeleton right, not the fine detail. What carries the test, given the
phrasing:

- Right adaptor per system: this is a three-target integration, so openmrs,
  dhis2 and fhir should each be used for their own system (the rubric's
  "picked the right adaptor for each system involved"). Substituting generic
  http calls for a system that has a dedicated adaptor, or using one adaptor
  for another's system, is the kind of clear issue we want caught.
- "When a new patient form comes in" pins an event-driven shape: a webhook
  trigger, not a cron poll.
- "Without duplicates" requires a lookup in OpenMRS before writing, with
  create happening only when no match is found (update or skip otherwise).
- "Then also send them" gives an ordering: the DHIS2 and FHIR sends happen
  after the OpenMRS save, not before or instead of it.

Everything else in the broader rubric (field validation, generated
identifiers, PII-free logging, downstream error handlers, exact
attribute/resource mapping) is not asked for in this phrasing: treat it as a
bonus if present and do not penalize its absence. Form fields and
instance-specific UUIDs (identifier types, org units, tracked entity types)
are unknown, so assumptions and clearly named placeholders are expected.
Hardcoded credentials would still be a clear issue.

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: step count and names, adaptor
versions, exact function signatures, the assumed form fields, and whether
create-vs-update is expressed as branch edges or as in-job logic may all
differ. Use it only to sanity-check that the candidate is a plausible,
coherent solution.

```yaml
name: patient-fanout
jobs:
  Prepare-submission:
    name: Prepare submission
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log(`Processing submission ${state.data?._id ?? '(no id)'}`);
        return { ...state, submission: state.data };
      });
  Upsert-patient-in-openmrs:
    name: Upsert patient in OpenMRS
    adaptor: "@openfn/language-openmrs@latest"
    body: |
      get('patient', { q: $.submission.national_id });

      fn((state) => {
        const matches = state.data?.results ?? [];
        console.log(`Lookup returned ${matches.length} match(es)`);
        return { ...state, existingPatient: matches[0] ?? null };
      });

      fn((state) => {
        const s = state.submission;
        const person = {
          names: [{ givenName: s.given_name, familyName: s.family_name }],
          gender: s.sex,
          birthdate: s.date_of_birth,
        };
        if (state.existingPatient) {
          return update(`person/${state.existingPatient.uuid}`, person)(state);
        }
        return create('patient', {
          identifiers: [
            {
              identifierType: state.identifierTypeUuid,
              identifier: s.national_id,
              location: state.locationUuid,
              preferred: true,
            },
          ],
          person,
        })(state);
      });
  Send-to-dhis2:
    name: Create tracked entity in DHIS2
    adaptor: "@openfn/language-dhis2@latest"
    body: |
      create('trackedEntityInstances', (state) => {
        const s = state.submission;
        return {
          trackedEntityType: state.trackedEntityTypeId,
          orgUnit: state.orgUnitId,
          attributes: [
            { attribute: state.givenNameAttributeId, value: s.given_name },
            { attribute: state.familyNameAttributeId, value: s.family_name },
          ],
        };
      });
  Send-to-fhir:
    name: Post Patient resource to FHIR
    adaptor: "@openfn/language-fhir@latest"
    body: |
      create('Patient', (state) => {
        const s = state.submission;
        return {
          resourceType: 'Patient',
          name: [{ given: [s.given_name], family: s.family_name }],
          gender: s.sex === 'M' ? 'male' : 'female',
          birthDate: s.date_of_birth,
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
  Prepare-submission->Upsert-patient-in-openmrs:
    condition_type: on_job_success
    enabled: true
    target_job: Upsert-patient-in-openmrs
    source_job: Prepare-submission
  Upsert-patient-in-openmrs->Send-to-dhis2:
    condition_type: on_job_success
    enabled: true
    target_job: Send-to-dhis2
    source_job: Upsert-patient-in-openmrs
  Send-to-dhis2->Send-to-fhir:
    condition_type: on_job_success
    enabled: true
    target_job: Send-to-fhir
    source_job: Send-to-dhis2
```

# quality_criteria

- A complete workflow is produced (assumptions and placeholder UUIDs or field names are fine), rather than only clarifying questions.
- The trigger is a webhook so the workflow runs per incoming patient form, not a cron poll.
- The right adaptor is used for each system: openmrs for the OpenMRS save, dhis2 for DHIS2, and fhir for the FHIR server.
- Before creating in OpenMRS, a step looks the patient up to check for an existing record; create only happens when no match is found, with update or skip otherwise, and exactly one of those outcomes applies per submission.
- The DHIS2 and FHIR sends run after the OpenMRS save succeeds, matching "then also send them".
- Job code uses real adaptor functions with plausible arguments, not invented ones, and each step returns state.
- Credentials are left to the adaptor configuration, never hardcoded in job code.
- Do not require validation steps, generated identifiers, PII-safe logging or downstream error handlers; the user did not ask for them in this phrasing (they are fine to include).

# turn

## role

user

## content

When a new patient form comes in, save the patient to OpenMRS without duplicates, then also send them to DHIS2 and a FHIR server.
