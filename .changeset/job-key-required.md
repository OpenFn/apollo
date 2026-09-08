---
"apollo": patch
---

Global chat: a job code call must name the step it edits. Without a key there
was nothing to stitch the result into, so the subagent still ran, wrote code,
and the planner dropped it — reaching the user as a reply that talks about a
change that was never made. `job_key` is now required, and both execution paths
refuse before spending the call rather than after. When a key does not match,
the error names the workflow's actual step keys so the planner can correct
itself in the same turn
