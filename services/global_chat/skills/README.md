# Standard skills

One folder per skill, entry point `SKILL.md`, in Anthropic's Agent Skills
format: YAML frontmatter (`name`, `description`) then the instructions. The
format matches what a user-defined skill will look like in v1, so a built-in
and a custom skill are the same artifact.

Invoked by name via the `skill` payload field, which bypasses the router and
hands the turn to the planner. The planner can also load a skill itself, through
its `load_skill` tool, when a request matches the skill's description.

Only `SKILL.md` is read. Add a file-read tool before bundling reference files.
