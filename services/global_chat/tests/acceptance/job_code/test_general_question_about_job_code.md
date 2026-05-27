---
id: global-chat.job-code.general-question
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

User is on a job step page but asks a general OpenFn concept question rather than a question specifically about their existing code (the difference between `fn` and `each`). The page context primes the answer toward concepts the user actually has in front of them, but the answer itself is general. No code modification is expected.

# quality_criteria

- The response explains what `fn()` and `each()` do in OpenFn and the difference between them — `each` iterates an array with a JSONPath, `fn` is a single state-transforming step.
- The response does NOT propose modifying the user's existing code; it explains concepts.
- If examples are given inline in prose, they look like valid OpenFn (no top-level imports, no `)(state)`, callbacks return state).

# settings

## page

workflows/dhis2-tracker-sync/transform-cases-to-tei

## workflow_yaml

```yaml
name: dhis2-tracker-sync
jobs:
  fetch-cases-from-commcare:
    id: job-fetch-cc-id
    name: Fetch Cases from CommCare
    adaptor: "@openfn/language-commcare@2.6.4"
    body: |
      submissions({ formId: 'household-registration', limit: 200 });
  transform-cases-to-tei:
    id: job-transform-tei-id
    name: Transform Cases to TEIs
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const teis = state.data.map(c => ({
          trackedEntity: c.case_id,
          orgUnit: c.properties.facility_id,
          attributes: [
            { attribute: 'w75KJ2mc4zz', value: c.properties.given_name },
            { attribute: 'zDhUuAYrxNC', value: c.properties.family_name },
          ]
        }));
        return { ...state, teis };
      });
  import-tracked-entities-to-dhis2:
    id: job-import-dhis2-id
    name: Import Tracked Entities to DHIS2
    adaptor: "@openfn/language-dhis2@8.0.7"
    body: |
      each(
        $.teis,
        create('trackedEntityInstances', state => state.data)
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 2 * * *"
    enabled: true
edges:
  cron->fetch-cases-from-commcare:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-cases-from-commcare
    condition_type: always
    enabled: true
  fetch-cases-from-commcare->transform-cases-to-tei:
    id: edge-fetch-transform
    source_job: fetch-cases-from-commcare
    target_job: transform-cases-to-tei
    condition_type: on_job_success
    enabled: true
  transform-cases-to-tei->import-tracked-entities-to-dhis2:
    id: edge-transform-import
    source_job: transform-cases-to-tei
    target_job: import-tracked-entities-to-dhis2
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-general-question-0003

# turn

## role

user

## content

I'm a bit confused — when should I reach for fn() vs each() in an OpenFn job? Are they interchangeable?
