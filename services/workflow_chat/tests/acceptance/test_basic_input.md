---
id: workflow-chat.basic-input
service: workflow_chat
judges: [general, openfn_workflow_expert]
---

# notes

Basic input test. The service handles a simple input without an existing YAML and either generates a workflow YAML or asks for more information.

# turn

## role

user

## content

Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.
