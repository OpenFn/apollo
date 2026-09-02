---
"apollo": patch
---

Global chat: the planner now streams the whole turn on the stream manager the
router passes in, instead of replacing it with a second one. That second
manager emitted its own `message_start` and restarted content block indices
mid-turn, and repeated the opening spinner. Also removes an unreachable
`call_job_code_agent` branch left behind when job code calls moved to the
concurrent path
