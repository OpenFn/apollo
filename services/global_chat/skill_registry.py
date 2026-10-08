"""Standard skill registry.

Standard skills ship with the agent: immutable, versioned in this repo, loaded
from disk once at import. They follow Anthropic's Agent Skills format (a folder
whose entry point is SKILL.md) so that a built-in and a user-defined skill are
the same artifact.

A malformed built-in raises here, at import, rather than on the request that
first invokes it.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from util import ApolloError

SKILLS_DIR = Path(__file__).parent / "skills"

# Subagents a skill can be written for, via `metadata.agent` in its frontmatter
SUBAGENTS = {"job_code"}


@dataclass(frozen=True)
class Skill:
    """A loaded SKILL.md: its frontmatter and its instructions."""

    name: str
    description: str
    body: str
    agent: str | None = None

    def as_block(self) -> str:
        """The instructions, tagged so a later turn can tell a skill is in use."""
        return f'<skill name="{self.name}">\n{self.body}\n</skill>'

    def as_preamble(self) -> str:
        """The skill as it is injected ahead of the request that invoked it."""
        return f"{self.as_block()}\n\nThe user invoked /{self.name}."

    def as_subagent_preamble(self) -> str:
        """The skill as it is injected ahead of the planner's message to a subagent."""
        return f"{self.as_block()}\n\nThe request below overrides these instructions where they conflict."


def _parse_skill_file(path: Path, folder: str) -> Skill:
    text = path.read_text()

    if not text.startswith("---"):
        raise ValueError(f"{path} has no YAML frontmatter")

    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter) or {}

    name = meta.get("name")
    description = meta.get("description")

    # The folder name is what a slash command resolves against, so a
    # frontmatter name that disagrees with it would be unreachable.
    if name != folder:
        raise ValueError(f"{path} declares name '{name}' but lives in '{folder}/'")
    if not description:
        raise ValueError(f"{path} has no description")
    if not body.strip():
        raise ValueError(f"{path} has no instructions")

    agent = (meta.get("metadata") or {}).get("agent")
    if agent is not None and agent not in SUBAGENTS:
        raise ValueError(f"{path} targets unknown agent '{agent}'")

    return Skill(name=name, description=description, body=body.strip(), agent=agent)


def _load_skills() -> dict[str, Skill]:
    return {
        entry.name: _parse_skill_file(entry / "SKILL.md", entry.name)
        for entry in sorted(SKILLS_DIR.iterdir())
        if entry.is_dir()
    }


_ALL_SKILLS = _load_skills()

# What users invoke and the planner loads. A skill written for a subagent is
# only ever attached to that subagent's calls.
SKILLS = {name: skill for name, skill in _ALL_SKILLS.items() if skill.agent is None}
JOB_AGENT_SKILLS = {name: skill for name, skill in _ALL_SKILLS.items() if skill.agent == "job_code"}


def job_agent_skills(attached: str | None = None) -> list[dict]:
    """The job agent's skills in job_chat's payload shape, leaving out one
    already attached to the message so it isn't offered twice."""
    return [
        {"name": skill.name, "description": skill.description, "body": skill.body}
        for skill in JOB_AGENT_SKILLS.values()
        if skill.name != attached
    ]


def get_skill(name: str) -> Skill:
    """Resolve a skill name, or reject the request."""
    skill = SKILLS.get(name)
    if skill is None:
        raise ApolloError(
            400,
            f"Unknown skill '{name}'",
            "UNKNOWN_SKILL",
            {"available": sorted(SKILLS)},
        )
    return skill


_SKILL_BLOCK = re.compile(r'<skill name="[^"]+">')


def has_skill(history: list[dict]) -> bool:
    """Whether a skill was invoked or loaded earlier in the conversation."""
    return any(
        turn.get("role") == "user"
        and isinstance(turn.get("content"), str)
        and _SKILL_BLOCK.search(turn["content"])
        for turn in history
    )


def strip_invocation(content: str, name: str) -> str:
    """Drop the leading /name token, leaving what the user actually asked.

    Only at the start of the message, and only the invoked skill's own name:
    the command was recognised by the client, so this is not command parsing.
    """
    return re.sub(rf"^\s*/{re.escape(name)}(?=\s|$)", "", content, count=1).lstrip()
