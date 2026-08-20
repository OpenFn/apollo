---
id: global-chat.gold.patient-fanout-verbose
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Verbose phrasing of the large fan-out pattern: a webhook-delivered
registration event is validated, deduplicated against OpenMRS, created or
updated there (with a generated identifier on the create path), then fanned
out to DHIS2 and a FHIR server, with error paths for invalid input and
downstream failures. The user spells everything out, so the response should
honor the explicit instructions. The ones that carry the test:

- "Do not add a fetch step" is explicit: the event arrives in `state.data`
  via webhook, so an added fetch from the source system is a clear failure.
- The idgen requirement is called out hard in the prompt: the OpenMRS ID has a
  check digit and "must be generated, not made up". Code that fabricates an ID
  (random string, timestamp, national ID reused as the OpenMRS ID) instead of
  requesting one from the idgen source is a clear failure. On the create path
  the generated ID is the preferred identifier and the national ID is a
  second, non-preferred identifier.
- Validation gates the writes: missing required fields (given name, family
  name, sex 'M'/'F', date of birth, national ID) fail the run to an
  invalid-input handler, and invalid events must never reach any write step.
- Ordering and convergence: DHIS2 and FHIR run only after the OpenMRS write
  succeeded, on either the create or the update path. Cross-standard mapping
  matters at the FHIR step: sex 'M'/'F' maps to gender 'male'/'female'.
- PII discipline is explicit: only the submission id is ever logged, never
  names, dates of birth or national IDs, including in both error handlers.

Because OpenFn workflows are trees (a step has one parent), candidates may
express create-vs-update as in-job conditional logic on a single path, or as
branch edges with the downstream fan-out duplicated under each branch. Either
is acceptable as long as the paths are mutually exclusive and the fan-out runs
after either one. Similarly the downstream-error handling may be one handler
per failing step or any equivalent arrangement.

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: job names, adaptor versions,
exact function signatures (especially the idgen call and the DHIS2/FHIR
payload details), and how branches and error routes are wired may all differ.
Placeholder UUIDs are expected since the prompt says identifier type,
location, org unit, program and attribute UUIDs are configured separately. Use
it only to sanity-check that the candidate is a plausible, coherent solution;
we want to catch clear issues against the explicit instructions above, not
enforce this exact structure. Pagination and idempotency concerns from the
broader rubric are not relevant to this single-event pattern.

```yaml
name: patient-registration-fanout
jobs:
  Validate-event:
    name: Validate registration event
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        const s = state.data;
        const required = ['given_name', 'family_name', 'sex', 'date_of_birth', 'national_id'];
        const missing = required.filter((f) => !s?.[f]);
        if (missing.length > 0 || !['M', 'F'].includes(s.sex)) {
          console.log(`Submission ${s?._id ?? '(no id)'} failed validation`);
          throw new Error('Invalid registration event');
        }
        console.log(`Submission ${s._id} validated`);
        return { ...state, submission: s };
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
        return post(
          `idgen/identifiersource/${state.idgenSourceUuid}/identifier`,
          { comment: 'OpenFn registration' }
        )(state).then((next) => {
          const generatedId = next.data?.identifier;
          return create('patient', {
            identifiers: [
              {
                identifierType: next.openmrsIdTypeUuid,
                identifier: generatedId,
                location: next.locationUuid,
                preferred: true,
              },
              {
                identifierType: next.nationalIdTypeUuid,
                identifier: next.submission.national_id,
                preferred: false,
              },
            ],
            person,
          })(next);
        });
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
  Log-invalid-input:
    name: Log invalid input
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log('Event rejected by validation; no data written');
        return state;
      });
  Log-dhis2-failure:
    name: Log DHIS2 sync failure
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log('DHIS2 write failed after OpenMRS registration; flag for retry');
        return state;
      });
  Log-fhir-failure:
    name: Log FHIR sync failure
    adaptor: "@openfn/language-common@latest"
    body: |
      fn((state) => {
        console.log('FHIR write failed after OpenMRS registration; flag for retry');
        return state;
      });
triggers:
  webhook:
    type: webhook
    enabled: true
edges:
  webhook->Validate-event:
    condition_type: always
    enabled: true
    target_job: Validate-event
    source_trigger: webhook
  Validate-event->Upsert-patient-in-openmrs:
    condition_type: on_job_success
    enabled: true
    target_job: Upsert-patient-in-openmrs
    source_job: Validate-event
  Validate-event->Log-invalid-input:
    condition_type: on_job_failure
    enabled: true
    target_job: Log-invalid-input
    source_job: Validate-event
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
  Send-to-dhis2->Log-dhis2-failure:
    condition_type: on_job_failure
    enabled: true
    target_job: Log-dhis2-failure
    source_job: Send-to-dhis2
  Send-to-fhir->Log-fhir-failure:
    condition_type: on_job_failure
    enabled: true
    target_job: Log-fhir-failure
    source_job: Send-to-fhir
```

# quality_criteria

- The trigger is a webhook and there is no added fetch step; the registration event is consumed from `state.data` as the user explicitly instructed.
- A validation step checks the five required fields (given name, family name, sex as 'M' or 'F', date of birth, national ID) and fails the run to an invalid-input handler when any are missing; invalid events never reach any write step.
- A step looks the patient up in OpenMRS by national ID before any write, and the create and update outcomes are mutually exclusive (via branch edges or in-job logic).
- On the create path, the OpenMRS ID is obtained from the idgen source rather than fabricated in code, and it becomes the preferred identifier with the national ID as a second, non-preferred identifier.
- On the update path, only demographics are modified and identifiers are not resent.
- After the OpenMRS write succeeds on either path, a DHIS2 tracked entity instance is created (name attributes, org unit, tracked entity type) and then a FHIR Patient resource is POSTed, with the sex code mapped to the FHIR gender value set (M to male, F to female).
- A DHIS2 or FHIR failure routes to downstream-error handling that logs a PII-free message; the workflow does not silently succeed past a failed write.
- The named adaptors are used for their systems (common, openmrs, dhis2, fhir); instance-specific UUIDs appear as placeholders or state/config references, credentials are never hardcoded, and no names, dates of birth or national IDs appear in any log.

# turn

## role

user

## content

Build an event-driven workflow that registers a patient across three systems.
Trigger: a webhook. KoboToolbox posts one registration event as the request body via its REST Service, so the data is already in state.data. Do not add a fetch step.
Steps: Validate the event. Required fields are given name, family name, sex ('M' or 'F'), date of birth, and national ID. If any are missing, fail the run so it routes to an invalid-input handler. Only log the submission id, never the personal fields. Look up the patient in OpenMRS by national ID to check whether they already exist. If they do not exist: generate a valid OpenMRS ID from the idgen source (it is required and has a check digit, so it must be generated, not made up), then create the patient with the generated OpenMRS ID as the preferred identifier and the national ID as a second, non-preferred identifier that has no check-digit rule. If they already exist: update their demographics only. Do not resend identifiers. After the OpenMRS write succeeds (either path), create a DHIS2 tracked entity instance for the patient with their name attributes, org unit, and tracked entity type. Then convert the patient to a FHIR Patient resource and POST it to the FHIR server. Map the sex code to the FHIR gender value set (M to male, F to female). If either the DHIS2 or FHIR write fails, route to a downstream-error handler that logs a PII-free message for retry.
Use common for validation and logging, openmrs for the OpenMRS steps, dhis2 for the tracked entity, and fhir for the FHIR resource. Do not hardcode credentials. Do not log names, dates of birth, or national IDs anywhere. Identifier type, location, org unit, program, and attribute UUIDs are instance-specific and configured separately.
