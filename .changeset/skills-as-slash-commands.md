---
"apollo": minor
---

global_chat: accept a `skill` field naming a standard skill the user invoked by slash command. `/diagnose` and `/qa` ship with the agent; an invoked skill skips the router and leads the planner's turn. Skill instructions are per-turn, so the client re-sends `skill` on every turn it applies to
