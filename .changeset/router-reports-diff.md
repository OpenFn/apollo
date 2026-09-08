---
"apollo": patch
---

Global chat: the router's direct job-code route now reports whether the edits
landed, in the same shape the planner does (`meta.subagent_calls[].diff`). That
route is the shortcut for a single-step edit, so it is the common case, and it
was discarding the diff — leaving a client unable to tell a reply that changed
nothing from one that changed something. Also hardened the YAML helpers: the
workflow is a client payload, and one that parsed to something other than a
mapping of jobs would raise rather than reach an error message
