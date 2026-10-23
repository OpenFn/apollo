---
id: global-chat.skills.specific-change-stays-specific
service: global_chat
judges: [general]
---

# notes

Same step as the review test, but the user asks for one specific change. This
is the negative case: the job agent should make the change, not run a full
review. Mentioning one serious problem it noticed is fine, briefly; a full
review of the step, or fixing things the user didn't ask about, is not.

# quality_criteria

- The upload step now maps the field to `gender` instead of `sex`.
- No other part of the code is changed. Judge the code itself: the workflow YAML may come back re-serialised (quoting, block style), which doesn't count as a change.
- The reply stays focused on the requested change rather than giving a full review of the step's other problems; at most it briefly mentions one.

# settings

## page

workflows/patient-sync/upload-patients

## workflow_yaml

```yaml
name: patient-sync
jobs:
  fetch-patients:
    id: job-fetch-patients-id
    name: Fetch patients
    adaptor: "@openfn/language-http@7.0.0"
    body: |
      get('https://example.org/api/patients');
      fn(state => ({ ...state, patients: state.data.results }));
  upload-patients:
    id: job-upload-patients-id
    name: Upload patients
    adaptor: "@openfn/language-http@7.0.0"
    body: |
      each(
        $.patients,
        post('https://target.example.org/api/people', state => {
          console.log('Uploading patient', state.data.name, state.data.phone);
          return {
            name: state.data.name,
            sex: state.data.gender,
            registered: '2024-01-01',
          };
        }).catch((error, state) => state)
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
      "[HTTP] GET https://example.org/api/patients - 200 in 280ms",
      "[R/T] Completed step Fetch patients in 350ms",
      "[R/T] Starting step Upload patients",
      "[JOB] Uploading patient <redacted> <redacted>",
      "[HTTP] POST https://target.example.org/api/people - 201 in 190ms",
      "[R/T] Completed step Upload patients in 410ms"
    ]
  }
]
```

## meta.session_id

sess-skills-specific-change-0001

# turn

## role

user

## content

Rename the sex field to gender in the upload
