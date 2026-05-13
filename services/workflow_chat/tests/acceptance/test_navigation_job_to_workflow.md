---
id: workflow-chat.navigation-job-to-workflow
service: workflow_chat
---

# notes

User has just navigated from a job-code editor (where they were discussing HTTP error handling) to a workflow editor and asks to add a new step. The model should infer the context switch and respond about the workflow as a structure, not continue talking about job-code error handling.

# quality_criteria

- The response talks about the workflow as a structure (jobs, edges, triggers), not about job-code-level error handling.
- The tone is warm and collaborative, not clinical or terse.
- The response adds a new email-sending step to the workflow (gmail, mailgun, or similar adaptor) and the rationale is plausible — e.g. notification, summary, or alerting.

# settings

## existing_yaml

```yaml
name: data-pipeline
jobs:
  fetch-source-data:
    id: job-fetch-id
    name: Fetch Source Data
    adaptor: '@openfn/language-http@6.5.4'
    body: 'get("https://source.api/data");'
  transform-data:
    id: job-transform-id
    name: Transform Data
    adaptor: '@openfn/language-common@latest'
    body: 'fn(state => { return { ...state, transformed: true }; });'
  save-to-database:
    id: job-save-id
    name: Save to Database
    adaptor: '@openfn/language-http@6.5.4'
    body: 'post("https://db.api/save", state => state.data);'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->fetch-source-data:
    id: edge-webhook-fetch-id
    source_trigger: webhook
    target_job: fetch-source-data
    condition_type: always
    enabled: true
  fetch-source-data->transform-data:
    id: edge-fetch-transform-id
    source_job: fetch-source-data
    target_job: transform-data
    condition_type: on_job_success
    enabled: true
  transform-data->save-to-database:
    id: edge-transform-save-id
    source_job: transform-data
    target_job: save-to-database
    condition_type: on_job_success
    enabled: true
```

## context.page_name

data-pipeline

## meta.last_page

```json
{
  "type": "job_code",
  "name": "transform-data",
  "adaptor": "http"
}
```

# history

## turn

### role

user

### content

[pg:job_code/transform-data/http] Can you add error handling to this HTTP request?

## turn

### role

assistant

### content

I'll add try-catch error handling to catch any request failures in your HTTP job.

## turn

### role

user

### content

[pg:job_code/transform-data/http] Also add retry logic with backoff

## turn

### role

assistant

### content

I'll add exponential backoff retry logic to handle transient failures.

# turn

## role

user

## content

Add a step to send the results via email
