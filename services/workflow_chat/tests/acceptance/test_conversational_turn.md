---
id: workflow-chat.conversational-turn
service: workflow_chat
judges: [general, openfn_workflow_expert]
---

# notes

User asks a conversational question that should not lead to YAML changes. The service should respond with text only, or with a YAML identical to the existing one.

# quality_criteria

- The response engages conversationally with the user's request for clarification, without unnecessarily restructuring or rewriting the workflow.

# settings

## existing_yaml

```yaml
name: fridge-statistics-processing
jobs:
  parse-and-aggregate-fridge-data:
    id: job-parse-id
    name: Parse and Aggregate Fridge Data
    adaptor: '@openfn/language-common@latest'
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

Can you explain that better
