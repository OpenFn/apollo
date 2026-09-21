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


@dataclass(frozen=True)
class Skill:
    """A loaded SKILL.md: its frontmatter and its instructions."""

    name: str
    description: str
    body: str

    def as_preamble(self) -> str:
        """The skill as it is injected ahead of the user's request."""
        return (
            f'<skill name="{self.name}">\n{self.body}\n</skill>\n\n'
            f"The user invoked the /{self.name} skill. Follow its instructions for this turn."
        )


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

    return Skill(name=name, description=description, body=body.strip())


def _load_skills() -> dict[str, Skill]:
    return {
        entry.name: _parse_skill_file(entry / "SKILL.md", entry.name)
        for entry in sorted(SKILLS_DIR.iterdir())
        if entry.is_dir()
    }


SKILLS = _load_skills()


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


def strip_invocation(content: str, name: str) -> str:
    """Drop the leading /name token, leaving what the user actually asked.

    Only at the start of the message, and only the invoked skill's own name:
    the command was recognised by the client, so this is not command parsing.
    """
    return re.sub(rf"^\s*/{re.escape(name)}(?=\s|$)", "", content, count=1).lstrip()
