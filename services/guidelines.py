"""Loader for the job and workflow guidelines in the top-level `guidelines/` folder.

The guidelines are content rather than code, so they live outside `services/`
as Markdown. Each scope is a folder of rule files under `guidelines/rules/`
(`job`, `workflow`), and each file starts with YAML frontmatter:

    ---
    id: execution-model
    order: 30
    ---

Files render in ascending `order`, never in directory-listing order, which
differs between filesystems. job_chat sets a prompt-cache breakpoint straight
after the rendered guide, so the bytes have to be identical on every machine
and every process start.

A file's text after the frontmatter is used as is, minus trailing newlines,
and the files are joined with a single newline. A blank line between the
frontmatter and the text therefore renders as a blank line before that block.

A rule file may contain the `{name_rule}` token, which renders as the active
step-name rule from `name_rules`, the same token the workflow prompt and the
judges already use.

The folder is located relative to this file, not the working directory. The
Docker image must copy `guidelines/` alongside `services/`; a missing copy
would only show up in the deployed image, so a missing folder, scope or
`order` raises rather than rendering an empty prompt.
"""

from pathlib import Path

import yaml
from name_rules import describe_rule_for_prompt

GUIDELINES_DIR = Path(__file__).resolve().parent.parent / "guidelines"

NAME_RULE_TOKEN = "{name_rule}"

_FRONTMATTER_DELIMITER = "---\n"


def _read_rule(path: Path) -> tuple[int, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_DELIMITER):
        raise ValueError(f"Guideline {path} has no frontmatter")

    end = text.find("\n" + _FRONTMATTER_DELIMITER, len(_FRONTMATTER_DELIMITER) - 1)
    if end == -1:
        raise ValueError(f"Guideline {path} has unterminated frontmatter")

    meta = yaml.safe_load(text[len(_FRONTMATTER_DELIMITER):end + 1]) or {}
    order = meta.get("order")
    if not isinstance(order, int):
        raise ValueError(f"Guideline {path} needs an integer `order` in its frontmatter")

    body = text[end + 1 + len(_FRONTMATTER_DELIMITER):]
    return order, body.rstrip("\n")


def render_for_prompt(scope: str) -> str:
    """Render every rule file in `guidelines/rules/<scope>/` as prompt text."""
    scope_dir = GUIDELINES_DIR / "rules" / scope
    if not scope_dir.is_dir():
        raise FileNotFoundError(f"No guidelines found for scope '{scope}' at {scope_dir}")

    rules = [_read_rule(path) for path in scope_dir.glob("*.md")]
    if not rules:
        raise FileNotFoundError(f"No guideline files found for scope '{scope}' in {scope_dir}")

    orders = [order for order, _ in rules]
    if len(set(orders)) != len(orders):
        raise ValueError(f"Guidelines for scope '{scope}' share an `order` value: {sorted(orders)}")

    rendered = "\n".join(body for _, body in sorted(rules))
    return rendered.replace(NAME_RULE_TOKEN, describe_rule_for_prompt())
