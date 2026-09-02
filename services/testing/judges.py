"""Registry of named acceptance-test judges.

Each judge is a `(role, rules)` pair defined in
`services/testing/judges/<name>.md`. The file uses two top-level sections:

    # role
    <prose: who the judge is and what it evaluates>

    # rules
    - bullet rules that apply to every evaluation under this judge

To add a new judge: drop a new markdown file in `services/testing/judges/`
and reference its filename (without `.md`) in a spec's `judges:` frontmatter
field. Default judge is `general`.
"""

from dataclasses import dataclass
from pathlib import Path


_JUDGES_DIR = Path(__file__).parent / "judges"


@dataclass
class JudgeConfig:
    name: str
    role: str
    rules: str


def load_judge(name: str) -> JudgeConfig:
    """Load a judge config from `services/testing/judges/<name>.md`.

    Raises FileNotFoundError if the file doesn't exist.
    """
    path = _JUDGES_DIR / f"{name}.md"
    if not path.exists():
        available = sorted(p.stem for p in _JUDGES_DIR.glob("*.md"))
        raise FileNotFoundError(
            f"Judge '{name}' not found at {path}. Available: {available}"
        )
    text = path.read_text()
    return JudgeConfig(
        name=name,
        role=_extract_section(text, "role").strip(),
        rules=_extract_section(text, "rules").strip(),
    )


def _extract_section(text: str, section_name: str) -> str:
    """Pull the body under `# <section_name>` up to the next `# ` header."""
    marker = f"# {section_name}".lower()
    lines = text.splitlines()
    in_section = False
    out: list[str] = []
    for line in lines:
        if line.strip().lower() == marker:
            in_section = True
            continue
        if in_section and line.startswith("# "):
            break
        if in_section:
            out.append(line)
    return "\n".join(out)
