---
"apollo": patch
---

global_chat: raise the planner's tool-call budget to 20, and end a run that spends it with a summary instead of stopping mid-narration. The context trim threshold moves above the budget so the summary is not written against a history that has just been cleared
