---
id: workflow-chat.edit-job-code
service: workflow_chat
judges: [general, openfn_workflow_expert]
---

# notes

User asks workflow_chat to fill in job code, which is not its responsibility. The service should politely explain that and avoid generating or modifying actual job bodies. Any returned YAML should be unchanged from the existing one (or absent).

# quality_criteria

- The response politely explains that filling in job code is not workflow_chat's responsibility, or otherwise declines the request gracefully.
- The response does not attempt to write actual job code into the workflow.

# settings

## existing_yaml

```yaml
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
    body: 'print("hello a")'
  upload-to-redis:
    id: job-upload-id
    name: Upload to Redis Collection
    adaptor: '@openfn/language-redis@latest'
    body: 'print("hello a")'
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

# turn

## role

user

## content

Can you also fill in the job code for all the steps
