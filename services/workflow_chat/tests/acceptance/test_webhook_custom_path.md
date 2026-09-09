---
id: workflow-chat.webhook-custom-path
service: workflow_chat
judges: [general, openfn_workflow_expert]
---

# notes

A webhook trigger's `custom_path` names its public URL: the trigger answers at `/i/<project-id>/<custom_path>` as well as at `/i/<trigger-id>`. Anything already posting to that URL depends on the name, so an edit that never mentions the trigger must not drop it. The user here asks to add a step, which has nothing to do with the trigger.

# quality_criteria

- The webhook trigger still carries `custom_path: et-emr-facility-001`, unchanged.
- The trigger keeps its `id` and stays a webhook trigger.
- No `custom_path` is invented for any other trigger.
- The requested step is added and wired in after the existing one.

# settings

## existing_yaml

```yaml
name: facility-intake
jobs:
  parse-submission:
    id: job-parse-id
    name: Parse Submission
    adaptor: '@openfn/language-common@latest'
    body: 'print("parse")'
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: false
    custom_path: et-emr-facility-001
edges:
  webhook->parse-submission:
    id: edge-webhook-parse-id
    source_trigger: webhook
    target_job: parse-submission
    condition_type: always
    enabled: true
```

# history

## turn

### role

user

### content

When a facility sends a submission, parse it.

## turn

### role

assistant

### content

I've set up a webhook-triggered workflow that parses each submission as it arrives.

# turn

## role

user

## content

Add a step after that one which writes the parsed data to PostgreSQL.
