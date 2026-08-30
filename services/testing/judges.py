"""Registry of named acceptance-test judges.

Each judge is a `(role, rules)` pair defined in
`services/testing/judges/<name>.md`. The file uses two top-level sections:

    # role
    <prose: who the judge is and what it evaluates>

    # rules
    - bullet rules that apply to every evaluation under this judge

The token `{name_rule}` in either section is replaced at load time with the
active step-name rule, so the judges never restate it as static prose.

To add a new judge: drop a new markdown file in `services/testing/judges/`
and reference its filename (without `.md`) in a spec's `judges:` frontmatter
field. Default judge is `general`.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from name_rules import describe_rule_for_judge

_JUDGES_DIR = Path(__file__).parent / "judges"

#: Placeholder in a judge markdown file, replaced with the active step-name
#: rule at load time. A judge that restated the rule as static prose would go
#: stale the moment APOLLO_UNICODE_STEP_NAMES moved, and would then either pass
#: names the sanitizer mangles or fail names it correctly leaves alone.
_NAME_RULE_TOKEN = "{name_rule}"

#: A bare `{lower_snake_case}` run. Prose and code samples in these files use
#: braces freely (`create({ name: $.x })`, `() => {}`), but never in this shape.
_PLACEHOLDER = re.compile(r"\{[a-z_][a-z0-9_]*\}")


def _reject_unsubstituted_placeholders(name: str, path: Path, text: str) -> None:
    """Raise if any placeholder survived substitution.

    Substitution is `str.replace`, which is a silent no-op when the token is
    misspelled. A judge that meant to state the active naming rule and instead
    stated nothing would grade every workflow name as acceptable, and nothing
    would say so. Not every judge needs the rule — the code-quality one grades
    job bodies — so a missing token is fine; a *mangled* one is not.
    """
    leftover = sorted(set(_PLACEHOLDER.findall(text)))
    if leftover:
        raise ValueError(
            f"Judge '{name}' ({path}) has unsubstituted placeholders: {', '.join(leftover)}. "
            f"The only one this loader fills is {_NAME_RULE_TOKEN}.",
        )


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
            f"Judge '{name}' not found at {path}. Available: {available}",
        )
    text = path.read_text().replace(_NAME_RULE_TOKEN, describe_rule_for_judge())
    _reject_unsubstituted_placeholders(name, path, text)
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
