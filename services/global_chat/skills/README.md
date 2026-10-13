# Standard skills

One folder per skill, entry point `SKILL.md`, in Anthropic's Agent Skills
format: YAML frontmatter (`name`, `description`) then the instructions. The
format matches what a user-defined skill will look like in v1, so a built-in
and a custom skill are the same artifact.

Invoked by name via the `skill` payload field, which bypasses the router and
hands the turn to the planner. The planner can also load a skill itself, through
its `load_skill` tool, when a request matches the skill's description.

A skill with `metadata: {agent: job_code}` in its frontmatter is written for
the job code agent. It can't be invoked or loaded by the planner; the planner
names it on a `call_job_code_agent` call, and its instructions are put ahead of
the planner's message, which overrides them where they conflict.

Only `SKILL.md` is read. Add a file-read tool before bundling reference files.
