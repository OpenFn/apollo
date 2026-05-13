---
id: workflow-chat.error-field
service: workflow_chat
---

# notes

The service is invoked with an `errors` field (replacing `content`) — used when the user's previous workflow attempt produced a validation error. The service should acknowledge the error and produce a corrected workflow.

# quality_criteria

- The response acknowledges the reported error rather than ignoring it.
- Any returned workflow YAML attempts to fix the cause of the error (in this case, an invalid adaptor).

# settings

## existing_yaml

```yaml
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-commons@latest'
    body: '| // Add data parsing and aggregation operations here'
  upload-to-redis:
    id: job-upload-id
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: '| // Add Redis collection upload operations here'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
edges:
  webhook->parse-and-aggregate-fridge-data:
    id: edge-webhook-parse-id
    source_trigger: webhook
    target_job: parse-and-aggregate-fridge-data
    condition_type: always
    enabled: true
  parse-and-aggregate-fridge-data->upload-to-redis:
    id: edge-parse-upload-id
    source_job: parse-and-aggregate-fridge-data
    target_job: upload-to-redis
    condition_type: on_job_success
    enabled: true
```

## errors

adaptor error

# history

## turn

### role

user

### content

Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.

## turn

### role

assistant

### content

I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.
