---
name: simulate-users
description: Try the Apollo AI assistant (global_chat, job_chat, workflow_chat) as a simulated user and report briefly how it went. Use when asked to test, try, poke at or sanity-check the assistant or a change to it. Pass a brief - what to test, why, and any recent changes.
context: fork
model: sonnet
---

# Simulate users

Call the assistant like a real user would. Report briefly. Improve this skill as you go.

## 1. Set up

- Run from the current Apollo checkout (worktree), so its code is what gets tested.
- Runs dir: `tmp/sim/` in the checkout (gitignored). Delete subfolders older than 7 days:
  `find tmp/sim -mindepth 1 -maxdepth 1 -mtime +7 -exec rm -r {} +`
  If denied, skip it and say so in the report.
- Make `<runs dir>/<YYYY-MM-DD>-<slug>/` for this run.

## 2. Decide what to test

- Read the brief. If it's vague, read `git diff main...HEAD` and `git diff` to see what changed.
- Name 1-3 adjacent things that could break and test those too (e.g. tool-call limit changed → also try a 5-turn convo).
- Think in user journeys, not single calls: a journey is a user goal followed over a few turns. Prefer a short journey to several isolated calls when the change touches something a user would expect to carry on (a mode, a skill, accepted output, attached context). Sometimes a single turn is enough.
- Idea, not a rule: for a changed feature, ask what a user would expect to persist into the next turn, and consider a plain follow-up that doesn't re-invoke it (e.g. "ok apply that"). Check the reply and the stored `history`.
- Mode, from the brief's wording:
  - **quick targeted**: 1-3 calls on the one thing.
  - **explore**: variations, looking for things to improve.
  - **thorough**: run the roles in `roles.md` (pre-deploy check).
- Budget: 10 turns (1 turn = 1 call) total unless the brief says otherwise. If more look needed, say so; don't run them.

## 3. Call

One turn = write a payload JSON, then run:

```
bun py <service> -i <dir>/<name>.in.json -o <dir>/<name>.out.json > <dir>/<name>.log 2>&1
```

- Default service `global_chat` (the router). Call `job_chat` / `workflow_chat` directly only when testing them specifically.
- Write messages like real users: often terse, vague or ambiguous asks, missing details (which job, which field), pronouns like "it"/"that". Keep at least one turn per run imperfect.
- Always set `"metrics_opt_in": false`.
- Stock context is in `fixtures/` (next to this file). Merge a fixture into the payload, or write your own yaml/code when needed.
- Payload keys:
  - `global_chat`: `content`, `history`, `workflow_yaml`, `page`, `attachments` (e.g. `[{"type":"log","content":"..."}]`)
  - `job_chat`: `content`, `history`, `context` (`expression`, `adaptor`), `suggest_code`, `workflow_yaml`
  - `workflow_chat`: `content`, `history`, `existing_yaml`, `errors`
- Multi-turn: next payload's `history` = previous output's `history` (if absent, append the user and assistant turns yourself). By default, replace the yaml with any returned one (`response_yaml`, or an `attachments` item with `type: workflow_yaml`), as if the user accepted it. Keep the old yaml only if the brief says the user rejected it.
- Repetitions: run independent calls in parallel (background).
- Output keys worth reading: `response`, `attachments`, `meta.agents`, `meta.subagent_calls`.
- If a call errors on payload shape, read `services/testing/spec_collector.py` and the service's `main()`. Nothing else.

## 4. Judge

Biggest red flags:
- **No answer arrives** (error, empty `response`, crash in `.log`), unless it's rate limiting (`RATE_LIMIT`, 429, overloaded). Suggests something is broken.
- **Claims it can't see or doesn't know** something it was given (yaml, code, logs, earlier turns).

- **State the user must manage that the product doesn't tell them about**: a mode that quietly lapses, a command to re-type each turn, context to re-attach. Ask as the user: "what would I assume happens next, and did it?" Put that line in `notes.md`.

Trace which agents and tools ran, in what order (`meta.agents`, `meta.subagent_calls`). Flag a path that's wrong, wasteful or surprising for the ask.

Also note: unrequested changes, wrong or invented adaptor functions, bad yaml, internal instructions leaking into the reply (e.g. "the user invoked /qa").

Write brief `notes.md` in the run dir.

## 5. Report

≤14 lines, no preamble:

```
Tested: <what, which service, how many calls/turns>
Overall: <one line: how it went>
Journeys: <one line each: user goal, turns, how it went (path: e.g. router → planner → job_chat ×2)>
✅/⚠️/❌ <finding> — "<≤15-word quote>" (<file>)
❓ <design question: works as coded but intended behaviour is unclear to a user>
...
Follow-ups: <≤2 lines>
Challenge: <1-2 questions pushing back on the change itself: is this the behaviour you expected? would X be better? would it break if the user did Y?>
Skill: <≤2 lines: suggested addition to this skill, roles.md or fixtures/, or "none">
```

Suggest a skill addition when something seemed worth retesting regularly, a fixture was missing, or a step here was unclear. Suggest, don't edit.
