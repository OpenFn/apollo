---
id: global-chat.skills.qa-whole-workflow
service: global_chat
judges: [general]
---

# notes

The user runs /qa on a two-step workflow before it goes live. The upload step
reads `$.patient_list`, but the fetch step writes `state.patients`, which is
why the last run failed. Both steps use `@latest`; the run log shows the
version they were tested on. /qa reviews and reports; it changes nothing until
the user asks. Judge the outcome: which side of the mismatch the fix changes
doesn't matter, and the report can take any reasonable shape.

# quality_criteria

- No job code or workflow YAML is changed; the reply proposes changes rather than making them.
- The reply names the key mismatch between the two steps as the cause of the crash and shows the fix.
- The reply recommends pinning each `@latest` adaptor to 7.0.0, the version the run log shows.
- The most serious problems come first, and the reply ends by offering to make the changes, without dwelling on not having made them.

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
