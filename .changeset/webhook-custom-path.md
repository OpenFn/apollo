---
"apollo": patch
---

workflow_chat: teach the model about a webhook trigger's `custom_path`, including
that removing the key leaves a saved path in place and only `custom_path: null`
clears it. The prompt carries the rules the server enforces and says not to
invent a value, since uniqueness is per project and Apollo never sees the project
