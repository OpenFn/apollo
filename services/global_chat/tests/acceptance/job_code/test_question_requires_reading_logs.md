---
id: global-chat.job-code.question-with-logs
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

User attaches the run logs from a failed execution and asks "why did this fail?". The logs show a 401 from OpenMRS due to an expired credential, NOT a problem with the job code itself. The assistant should diagnose from the logs and explain the failure cause; it should not invent a code fix for a problem that is actually a credentials/configuration issue. No unsolicited rewrite of the job body is expected.

# quality_criteria

- The response correctly identifies that the failure is a 401 / authentication problem against OpenMRS, drawing from the attached log content.
- The response points the user toward fixing the OpenMRS credential (re-authenticate / refresh credential), not toward changing the job code.
- The response does NOT silently rewrite the job code to "fix" an issue that isn't a code problem.

# settings

## page

workflows/openmrs-encounter-sync/post-encounters-to-openmrs

## workflow_yaml

```yaml
name: openmrs-encounter-sync
jobs:
  fetch-encounters-from-fhir:
    id: job-fetch-fhir-id
    name: Fetch Encounters from FHIR
    adaptor: "@openfn/language-fhir-4@0.1.10"
    body: |
      get('Encounter', { _lastUpdated: 'gt2025-01-01', _count: 50 });
      fn(state => {
        const encounters = state.data.entry?.map(e => e.resource) || [];
        return { ...state, encounters };
      });
  post-encounters-to-openmrs:
    id: job-post-openmrs-id
    name: Post Encounters to OpenMRS
    adaptor: "@openfn/language-openmrs@4.1.0"
    body: |
      each(
        $.encounters,
        create('encounter', state => ({
          patient: state.data.subject.reference.split('/')[1],
          encounterType: 'ADULTINITIAL',
          encounterDatetime: state.data.period.start,
          location: state.data.location?.[0]?.location?.reference
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 */6 * * *"
    enabled: true
edges:
  cron->fetch-encounters-from-fhir:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-encounters-from-fhir
    condition_type: always
    enabled: true
  fetch-encounters-from-fhir->post-encounters-to-openmrs:
    id: edge-fetch-post
    source_job: fetch-encounters-from-fhir
    target_job: post-encounters-to-openmrs
    condition_type: on_job_success
    enabled: true
```

## attachments

```json
[
  {
    "type": "log",
    "content": "[CLI] ✔ Loaded credential at openmrs-prod (last-rotated 2024-09-12)\n[R/T] Starting job post-encounters-to-openmrs\n[R/T] adaptor: @openfn/language-openmrs@4.1.0\n[JOB] Iterating over 12 encounters from state.encounters\n[JOB] POST /openmrs/ws/rest/v1/encounter\n[JOB] ✗ Request failed with status 401 Unauthorized\n[JOB]   response body: {\"error\":{\"message\":\"User is not logged in.\",\"code\":\"org.openmrs.api.APIAuthenticationException\"}}\n[JOB] ✗ Request failed with status 401 Unauthorized (patient: 5f8a-...)\n[JOB] ✗ Request failed with status 401 Unauthorized (patient: 7b21-...)\n[R/T] Job failed: AuthError: Request failed with status 401 Unauthorized\n[R/T]   at create (@openfn/language-openmrs/dist/index.js:124)\n[R/T] Job exited with error code 1"
  }
]
```

## meta.session_id

sess-job-code-question-with-logs-0004

# turn

## role

user

## content

This step failed in last night's run. Can you look at the logs and tell me why?
