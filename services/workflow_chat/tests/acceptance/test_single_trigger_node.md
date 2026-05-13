---
id: workflow-chat.single-trigger-node
service: workflow_chat
---

# notes

User asks for a change that implies multiple nodes coming directly from the trigger. Only one node can come from the trigger in OpenFn — the service should respect the constraint by picking one job to run first and branching from there, not by adding multiple direct children of the trigger.

# quality_criteria

- The proposed workflow respects the constraint that only one job can come directly from the trigger.
- If the user's request implies multiple parallel steps from the trigger, the response restructures it so one job runs first and the others branch off after.

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
    body: 'print("hello b")'
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

Actually I also want an email notification at the same time as the data is being parsed.
