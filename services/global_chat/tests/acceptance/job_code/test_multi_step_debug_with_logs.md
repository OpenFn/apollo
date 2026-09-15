---
id: global-chat.job-code.multi-step-debug-with-logs
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The user attaches a run log and asks why the LAST TWO steps failed. Naming two
steps means this cannot be the direct job_code_agent route — it goes to the
planner, which then calls the job code agent per step.

This is the attachment-passthrough case: the log must reach those subagent calls
as the exact bytes the user attached, not as the planner's paraphrase of them.
The log contains two distinct failures that only the log reveals —
`map-to-dhis2` crashed on `state.patients` being undefined, and
`load-to-dhis2` then failed because `state.data` was empty — so an answer built
from a summary rather than the log itself cannot get both right. The root cause
is upstream: `fetch-from-commcare` writes `state.cases`, and the mapping step
reads `state.patients`, a key nothing produces.

The failing key names (`state.patients`, `state.cases`) and the specific error
lines are the tell: they appear only in the log, so a response that quotes them
proves the log content travelled, while a vague "the steps failed due to missing
data" does not.

# quality_criteria

- The response identifies that `map-to-dhis2` failed because `state.patients` was undefined, referencing the actual error from the attached log.
- The response identifies that `load-to-dhis2` failed as a consequence — it received no records / `state.data` was empty — rather than treating the two failures as unrelated.
- The response traces the root cause to the key mismatch: the CommCare step writes `state.cases` while the mapping step reads `state.patients`.
- The response reflects the specifics of the attached log (error text, key names, step names) rather than a generic description of a failed run.
- The response does NOT claim it cannot see the logs, the run, or the other steps.

# settings

## page

workflows/commcare-to-dhis2/map-to-dhis2

## workflow_yaml

```yaml
name: commcare-to-dhis2
jobs:
  fetch-from-commcare:
    id: job-fetch-commcare-id
    name: Fetch from CommCare
    adaptor: "@openfn/language-commcare@3.0.4"
    body: |
      get('/api/v0.5/case/', { type: 'patient', limit: 100 });
      fn(state => {
        return { ...state, cases: state.data.objects || [] };
      });
  map-to-dhis2:
    id: job-map-dhis2-id
    name: Map to DHIS2
    adaptor: "@openfn/language-common@2.1.1"
    body: |
      fn(state => {
        const mapped = state.patients.map(p => ({
          trackedEntityType: 'nEenWmSyUEp',
          orgUnit: p.properties.owner_id,
          attributes: [
            { attribute: 'w75KJ2mc4zz', value: p.properties.first_name },
            { attribute: 'zDhUuAYrxNC', value: p.properties.last_name }
          ]
        }));
        return { ...state, data: mapped };
      });
  load-to-dhis2:
    id: job-load-dhis2-id
    name: Load to DHIS2
    adaptor: "@openfn/language-dhis2@6.2.0"
    body: |
      each(
        $.data,
        create('trackedEntityInstances', state => state.data)
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 2 * * *"
    enabled: true
edges:
  cron->fetch-from-commcare:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-from-commcare
    condition_type: always
    enabled: true
  fetch-from-commcare->map-to-dhis2:
    id: edge-fetch-map
    source_job: fetch-from-commcare
    target_job: map-to-dhis2
    condition_type: on_job_success
    enabled: true
  map-to-dhis2->load-to-dhis2:
    id: edge-map-load
    source_job: map-to-dhis2
    target_job: load-to-dhis2
    condition_type: always
    enabled: true
```

## attachments

```json
[
  {
    "type": "log",
    "content": "[R/T] Starting run for workflow commcare-to-dhis2\n[R/T] Starting job fetch-from-commcare\n[R/T] adaptor: @openfn/language-commcare@3.0.4\n[JOB] GET /api/v0.5/case/?type=patient&limit=100\n[JOB] ✔ 200 OK — 87 objects returned\n[R/T] Job fetch-from-commcare succeeded in 2.104s\n[R/T] Starting job map-to-dhis2\n[R/T] adaptor: @openfn/language-common@2.1.1\n[JOB] ✗ TypeError: Cannot read properties of undefined (reading 'map')\n[JOB]     at fn (/tmp/expression-2.js:2:34)\n[JOB]   state.patients was undefined at the time of the call\n[R/T] Job map-to-dhis2 failed: TypeError: Cannot read properties of undefined (reading 'map')\n[R/T] Edge map-to-dhis2->load-to-dhis2 condition 'always' met — continuing\n[R/T] Starting job load-to-dhis2\n[R/T] adaptor: @openfn/language-dhis2@6.2.0\n[JOB] each() received 0 items — state.data is empty\n[JOB] ✗ No trackedEntityInstances were created\n[R/T] Job load-to-dhis2 failed: nothing to create, state.data was empty\n[R/T] Run finished with errors (2 of 3 steps failed)"
  }
]
```

## meta.session_id

sess-job-code-multi-step-debug-with-logs-0001

# turn

## role

user

## content

Last night's run went bad — the last two steps both failed. I've attached the log. What went wrong?
