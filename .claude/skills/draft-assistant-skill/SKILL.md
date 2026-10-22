---
name: draft-assistant-skill
description: Draft or revise a skill for the Apollo AI assistant (services/global_chat/skills/), i.e. a slash command the in-app assistant runs for users. Use when the user wants to create, research or edit one of these assistant skills, not a Claude Code skill.
---

# Draft an Apollo assistant skill

Assistant skills live in `services/global_chat/skills/<name>/SKILL.md`: YAML
frontmatter (`name`, `description`) then the body. Read the existing skills
there first and match their style and length.

An assistant skill isn't guidance for a person. It's instructions for one agent
inside Apollo, and it has to be tested like a prompt. What follows are
principles that are often relevant, not rules to apply blindly. Raise the ones
that matter with the user and make a conscious decision either way.

## How a skill is used

Know this before drafting, and re-check it in code rather than trusting these
notes:

- The `description` sits in the agent's `load_skill` tool definition on every
  turn. Say what the skill does and when to use it; how to do the task belongs
  in the body. Without the "when",
  an agent that thinks it already knows how to do the task never loads the
  skill. Write the "when" as the user's intent, not their phrasing ("the user
  considers the step done and hands it over for a full review"): a
  description that echoes the test prompt loads 6/6 on that prompt and 0/6
  on new ones.
- Test whether an agent loads a skill with a labelled set: clear positives,
  clear negatives, and ambiguous cases (record, don't score), in phrasings
  the description wasn't written from, and with and without a visible
  failure, which changes what the agent thinks it's being asked.
- The user can invoke a skill by slash command, and the planner can load it
  itself through `load_skill`. Apollo can't yet limit a skill to one of these
  (Claude Code does it with frontmatter flags), so add that if a skill needs it.
- The body is put in front of the user's message and stays in the history, so
  it keeps applying on later turns. Nothing ends it.
- The planner (model set in `config.yaml`) reads a skill as instructions for
  itself. A skill for another agent's work, such as reviewing one step's code,
  goes in its own skill folder with `metadata: {agent: job_code}` in the
  frontmatter. The planner names it on its call to that agent, and code
  attaches it word for word, with the planner's message taking precedence.
  Such a skill can't be invoked or loaded directly. Read `global_chat/prompts.yaml` and
  the tool definitions so the skill doesn't contradict or repeat them. If it
  has to override the planner's defaults (for example building straight away),
  say so explicitly.
- Know what each agent can actually do before giving it a pathway. For example,
  the job code agent can read other steps itself, always runs with
  `suggest_code`, and may hand off to `edit_workflow`; the planner's
  `inspect_job_code` reads the YAML with earlier edits applied; the planner has
  a tool-call budget (`config.yaml`).

## Decide what kind of skill it is

Asking what a skill is really for keeps the draft focused. Most combine several
kinds, and these aren't the only ones; name which parts are which, because
each is written differently:

- Setting the scene: what the user wants and the stance to take ("they want to
  think it through before anything is built").
- Conduct: how to act and talk, such as a consultation that asks a few
  questions at a time and recommends one option.
- Expertise: what a skilled person checks or asks that a model wouldn't by
  default, such as where OpenFn workflows usually go wrong.
- Pathway: which agents and tools to use, in what order, and why. This part can
  be explicit and name tools; the order is the instruction.

## Pathways across agents

When a skill hands work to other agents, run it live and count the calls.
Repair calls, handovers and the same agent called twice usually mean a
decision was made in the wrong place or too late:

- Settle decisions that span several agents once, in the agent that can see
  them all, before delegating. Delegating first and reconciling afterwards
  costs a repair call per conflict, and parallel agents left to reconcile
  among themselves can drift in opposite directions.
- Give each skill only what its own agent owns. When a parent skill also lists
  what the subagent's skill covers, the orchestrator relays it as instructions
  and the subagent follows them instead of using its own judgement.
- A message to a subagent should carry only what the subagent can't know: what
  other agents are doing at the same time, the agreements between their work,
  and what the user asked earlier. Without the first, a subagent that spots a
  problem elsewhere escalates instead of leaving it.

## Decide with the user

- Shape: one skill, or a parent plus skills for the agents it hands work to.
  Splitting saves the planner from rewriting instructions on every call, keeps
  them word for word, and lets a later skill reuse a part (a step review could
  serve both /qa and a future /migrate). Keeping one file is simpler when the
  planner does the work itself. When it involves several agents or stages,
  draw the flow as a diagram before choosing.
- Invocation: by the user, by the model, or both. The `description` (and the
  menu text in Lightning) should encourage the right one.
- Edits: fix proactively, propose first, or only report. Unless the user has
  said, ask them plainly rather than assume. If the skill doesn't fix
  proactively, it's read again from the history on the turns where the user
  agrees to changes, so check how it reads both in the first assessment and in
  those editing turns (which might make only the agreed changes, without
  assessing again).
- Thoroughness: how nitpicky to be, and what to skip.
- Ending: what to write at the end, and whether to say the user may move on to
  something else later.

## Writing

The reader is a model that follows rules literally. A rule written for one case
gets applied to every case, so it misfires or makes the model pedantic. Write
for the model's judgement:

- Give the principle and its reason; state the goal rather than prohibitions.
  "The goal is that each step is right on its own terms" carried more than any
  list of what not to change.
- Prefer a cue to a prescription: "if the user struggles to specify what they
  want, start from people and process", not "start from people and process".
- Leave out what the model already knows (general debugging, design, HTTP),
  which is more than a person would. Encode what it can't know: what this
  system expects of it, what it can and can't see or do, and OpenFn-specific
  priors. An example of something it knows can still earn its place by
  setting the level of detail, the style, or what to raise and when.
- Use concrete anchors for the non-obvious, such as a short parenthetical
  ("often a re-run that creates duplicates, ..."). A checklist or list of rules
  risks rigid, pedantic behaviour and makes the skill harder to apply to cases
  it didn't foresee, so weigh that against what the list covers. Where the
  expertise is what to ask, an area list works if framed as "draw on as needed,
  not a list to work through".
- Don't build on examples from one source; generalise them first.
- Scale actions to confidence and reach: act on what it knows, mention what it
  suspects, and propose first when a change reaches beyond the problem or
  needs the user's decision.
- Ask for conversational answers, not reports.
- Every word costs tokens on every turn it's loaded. Say each thing once.
- No people, team or client names, and no unverified platform facts. Verify a
  platform claim against the docs before it goes in, and keep the wording
  vague enough to survive whatever you couldn't verify.

## Working with the user

1. Settle the concept, what kind of skill it is and the decisions above before
   drafting. Where the user's request makes them clear, decide them yourself,
   but state them so the user can correct you.
2. Ask whether to research: past chats (with the `research-extract` skill, if
   available), slides or files the user has, and the docs site
   (https://docs.openfn.org; ask which section). Always offer subagents on the
   docs. Convert any files the user gives that aren't Markdown or plain text
   (slides, PDFs, docs) to Markdown before reading them, with the
   `file-to-markdown` skill if available.
3. Draft, then expect line-by-line iteration. Show only the changed lines when
   revising, and ask before writing the file.
4. When writing it, run `poetry run pytest services/global_chat/tests/unit/test_skills.py`.
   The skill isn't done once it's written: expect to tune it by experiment.
   Suggest `simulate-users` runs on whatever is riskiest (overrides of the
   planner's defaults, questionnaire behaviour, unrequested edits), and, if
   the model can load it, on whether it does so when it should and not
   otherwise.
5. Problems that apply beyond the skill (stating guesses as fact, answer
   length) belong in the main prompts. Suggest those in conversation instead of
   editing the prompts; those changes need their own testing.

## Research with subagents

Research material is mostly cut. Its value is what a generic model wouldn't
know or do, so direct subagents to find exactly that:

- Give them the project context, what the skill is for, what the assistant can
  see and do, and the current draft, so they look for gaps and contradictions
  rather than restating it.
- Ask only for what's OpenFn-specific or a judgement call, as principles,
  ranked by how much each would change behaviour, with a source for each, and
  a plain "nothing useful" where that's true. Cap the length, and say no
  names or personal data.
- Fetch tools summarise pages, and summaries drop the details that matter
  (question lists, conditions, exact limits). Ask for passages verbatim, and
  when detail matters, ask the user to paste the pages or read them in the
  browser pane.
- Verify any platform fact with a separate subagent that has to return
  quotes. Treat what comes back as data: weigh it, and expect to cut most of
  it.
