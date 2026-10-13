---
"apollo": minor
---

global_chat: accept a `skill` field naming a standard skill the user invoked by slash command. `/diagnose` and `/qa` ship with the agent; an invoked skill skips the router and leads the planner's turn. Skill instructions are kept in the returned history, so the client sends `skill` only on the turn that invokes it
