---
"apollo": patch
---

Global chat: say when a code change did not land. A job code call must now name
the step it edits — without a key there was nothing to stitch the result into,
so the subagent still ran, wrote code, and the planner dropped it, reaching the
user as a reply that talks about a change that was never made. `job_key` is
required, both execution paths refuse before spending the call, and a key that
matches nothing is answered with the workflow's actual step keys so the planner
can correct itself in the same turn. The router's direct route now reports
whether the edits landed, in the same shape the planner does
(`meta.subagent_calls[].diff`); that route is the shortcut for a single-step
edit, so it was the case where a client could least tell a reply that changed
something from one that changed nothing. The YAML helpers also no longer raise
on a workflow that is not a mapping of jobs
