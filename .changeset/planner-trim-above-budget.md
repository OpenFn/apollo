---
"apollo": patch
---

Global chat: keep the context trim threshold above the planner's tool budget,
so a run that overshoots its budget with a parallel batch no longer clears the
workflow edits it is about to summarise
