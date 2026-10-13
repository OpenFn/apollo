---
id: global-chat.skills.step-review-when-done
service: global_chat
judges: [general]
---

# notes

The user considers the upload step finished and hands it over for review, from
the step's own page, so the request goes straight to the job code agent. Its
last run succeeded, so nothing visibly fails; the step has problems only a
review would catch. The job agent should pick up its qa-code skill and review
the step properly. A good reply may fix some problems and only flag others;
either is fine as long as each problem is dealt with. It may also check the
upstream step.

# quality_criteria

- The reply deals with patient personal data being written to the run logs (the console.log of names and phone numbers), by removing it or clearly flagging it.
- The reply deals with failures being silently swallowed (the `.catch` that just returns state), by fixing it or clearly flagging it.
- The reply deals with the hardcoded `registered: '2024-01-01'` date, by fixing it or flagging it as a value that shouldn't be hardcoded.
- Anything changed in the code stays within the upload step and is related to a problem the reply names.

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

sess-skills-step-review-when-done-0001

# turn

## role

user

## content

I think this step is done now. Can you review it before it goes live?
