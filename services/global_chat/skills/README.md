# Standard skills

One folder per skill, entry point `SKILL.md`, in Anthropic's Agent Skills
format: YAML frontmatter (`name`, `description`) then the instructions. The
format matches what a user-defined skill will look like in v1, so a built-in
and a custom skill are the same artifact.

Invoked by name via the `skill` payload field, which bypasses the router and
hands the turn to the planner.

**The bodies here are placeholders.** They exercise the mechanism; they are not
the real prompts. See https://github.com/OpenFn/apollo/issues/614.
