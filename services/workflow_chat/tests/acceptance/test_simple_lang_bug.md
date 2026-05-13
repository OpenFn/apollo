---
id: workflow-chat.simple-lang-bug
service: workflow_chat
---

# notes

User asks "are you there?" — the service should respond conversationally about itself. It should use simple, user-facing language and not mention internal data structures like YAML.

# quality_criteria

- The response describes the service's capabilities in plain, user-facing language.
- The response does not expose internal implementation details such as YAML, schemas, or data formats.

# turn

## role

user

## content

are you there?
