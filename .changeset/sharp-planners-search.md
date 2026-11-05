---
"apollo": patch
---

global_chat: planner searches before fetching, because web fetch only opens URLs already in the conversation, and reads web results correctly when it calls the web tools from code, so a refused fetch is no longer retried
