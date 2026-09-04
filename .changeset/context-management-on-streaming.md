---
"apollo": patch
---

Global chat: pass the context trim config on the streamed planner call as well
as the non-streamed one. Global chat streams, so the config only ever reached a
path production does not take. Both calls now share one definition
