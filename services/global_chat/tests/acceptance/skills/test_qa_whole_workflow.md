---
id: global-chat.skills.qa-whole-workflow
service: global_chat
judges: [general]
---

# notes

The user runs /qa on a two-step workflow and asks for its comments to be left
alone. The upload step reads `$.patient_list`, but the fetch step writes
`state.patients`, which is why the last run failed. Both steps use `@latest`;
the run log shows the version they were tested on. The planner hands each step
to the job code agent with its qa-code skill and fits the steps together
itself. Judge the outcome: which side of the mismatch changes doesn't matter as
long as the two steps agree, and the report can take any reasonable shape.

# quality_criteria

- After the changes, the upload step reads the patient list from the same key the fetch step writes it to, so the crash is fixed.
- The existing comment in the fetch step is still there and unchanged.
- Each `@latest` adaptor is pinned to 7.0.0, the version the run log shows, or the reply recommends pinning it to the tested version.
- The reply says what was fixed and what should still change, with the most serious problems first, and reminds the user to test the workflow again.

# settings

## page

workflows/patient-sync

## skill

```json
{"name": "qa"}
```

## workflow_yaml

```yaml
name: patient-sync
jobs:
  fetch-patients:
    id: job-fetch-patients-id
    name: Fetch patients
    adaptor: "@openfn/language-http@latest"
    body: |
      get('https://example.org/api/patients');
      // The API nests patients under results
      fn(state => ({ ...state, patients: state.data.results }));
  upload-patients:
    id: job-upload-patients-id
    name: Upload patients
    adaptor: "@openfn/language-http@latest"
    body: |
      each(
        $.patient_list,
        post('https://target.example.org/api/people', state => ({
          name: state.data.name,
          sex: state.data.gender,
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 2 * * *"
    enabled: true
edges:
  cron->fetch-patients:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-patients
    condition_type: always
    enabled: true
  fetch-patients->upload-patients:
    id: edge-fetch-upload
    source_job: fetch-patients
    target_job: upload-patients
    condition_type: on_job_success
    enabled: true
```

## attachments

```json
[
  {
    "type": "log",
    "content": [
      "[CLI] Versions: node 22, worker 1.x, @openfn/language-http 7.0.0",
      "[R/T] Starting step Fetch patients",
      "[HTTP] GET https://example.org/api/patients - 200 in 312ms",
      "[R/T] Completed step Fetch patients in 401ms",
      "[R/T] Starting step Upload patients",
      "[R/T] Error in runtime execution!",
      "[R/T] TypeError: Cannot read properties of undefined (reading 'length')",
      "    at each (@openfn/language-common)",
      "[R/T] Failed step Upload patients after 12ms"
    ]
  }
]
```

## meta.session_id

sess-skills-qa-whole-workflow-0001

# turn

## role

user

## content

/qa please review this before it goes live, and leave any comments alone
