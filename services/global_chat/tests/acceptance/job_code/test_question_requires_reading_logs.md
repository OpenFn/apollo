---
id: global-chat.job-code.question-with-logs
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

User attaches the run logs, input data, and last successful output from a failed execution. The logs show a 401 from OpenMRS due to an expired credential, NOT a problem with the job code itself. To diagnose confidently the assistant has to consult both the logs (auth failure on OpenMRS side) and the input (FHIR encounter records look structurally valid — `subject.reference`, `period.start`, etc. are all present) so it can rule out the data side. The previous successful output shows the workflow has worked before with the same code, reinforcing that the change is credential-side. No unsolicited rewrite of the job body is expected.

# quality_criteria

- The response correctly identifies that the failure is a 401 / authentication problem against OpenMRS, drawing from the attached log content.
- The response references the attached input/output data to rule out a data or code-shape problem (e.g. notes that the FHIR encounter records look structurally fine, or that the workflow produced successful results previously with the same code).
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
  },
  {
    "type": "input",
    "content": "{\n  \"encounters\": [\n    {\n      \"resourceType\": \"Encounter\",\n      \"id\": \"enc-001\",\n      \"status\": \"finished\",\n      \"subject\": { \"reference\": \"Patient/5f8a-1234-abcd\" },\n      \"period\": { \"start\": \"2025-04-12T09:15:00+00:00\" },\n      \"location\": [{ \"location\": { \"reference\": \"Location/clinic-east-wing\" } }]\n    },\n    {\n      \"resourceType\": \"Encounter\",\n      \"id\": \"enc-002\",\n      \"status\": \"finished\",\n      \"subject\": { \"reference\": \"Patient/7b21-5678-efgh\" },\n      \"period\": { \"start\": \"2025-04-12T10:30:00+00:00\" },\n      \"location\": [{ \"location\": { \"reference\": \"Location/clinic-west-wing\" } }]\n    },\n    {\n      \"resourceType\": \"Encounter\",\n      \"id\": \"enc-003\",\n      \"status\": \"finished\",\n      \"subject\": { \"reference\": \"Patient/3c44-9876-ijkl\" },\n      \"period\": { \"start\": \"2025-04-12T11:45:00+00:00\" },\n      \"location\": [{ \"location\": { \"reference\": \"Location/clinic-east-wing\" } }]\n    }\n  ]\n}"
  },
  {
    "type": "output",
    "content": "{\n  \"_lastSuccessfulRun\": \"2025-04-10T06:02:11Z\",\n  \"createdEncounters\": [\n    { \"uuid\": \"e1d8a4c0-3f12-4a3b-9b21-001\", \"patient\": \"5f8a-1234-abcd\" },\n    { \"uuid\": \"e1d8a4c0-3f12-4a3b-9b21-002\", \"patient\": \"7b21-5678-efgh\" },\n    { \"uuid\": \"e1d8a4c0-3f12-4a3b-9b21-003\", \"patient\": \"3c44-9876-ijkl\" }\n  ]\n}"
  }
]
```

## meta.session_id

sess-job-code-question-with-logs-0004

# turn

## role

user

## content

This step failed in last night's run. The logs mention 401s — is the FHIR data we got back malformed in some way, or is it something on the OpenMRS side? I've attached the logs, the input state, and the output from when it last ran successfully.
