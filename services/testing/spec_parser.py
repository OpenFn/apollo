"""Parse acceptance test markdown specs into Spec dataclasses.

Spec format (see `agent-team-architecture-plan/example-acceptance-md-spec.md`):

    ---
    id: ...
    service: ...
    runs: 1            # optional, default 1
    ---

    # notes
    prose description

    # quality_criteria
    - criterion 1
    - criterion 2

    # settings
    ## page
    workflows/...
    ## context.expression
    ```js
    some code
    ```
    ## suggest_code
    true

    # history
    ## turn
    ### role
    user
    ### content
    message
    ## turn
    ### role
    assistant
    ### content
    reply

    # turn
    ## role
    user
    ## content
    current message

Section semantics:
  - frontmatter: `id` (defaults to filename stem), `service` (required), `runs` (int, default 1).
  - `# notes`: free-form prose, used as `test_notes` for the judge.
  - `# quality_criteria`: bullet list, each `-` is one criterion.
  - `# settings`: each `## key.path` becomes a nested dict entry. JSON code fences are parsed;
    yaml/js/plain fences are kept as strings; `true`/`false` plain text becomes a bool.
  - `# history`: repeated `## turn` blocks, each with `### role` and `### content`.
  - `# turn`: the single current user message under test. Has `## role` and `## content`.
    May be omitted (e.g. workflow_chat error-correction tests where `errors` is the trigger).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class Spec:
    id: str
    service: str
    runs: int = 1
    notes: str = ""
    quality_criteria: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    current_turn: Optional[dict[str, str]] = None
    path: Optional[Path] = None


def parse_spec(path: Path) -> Spec:
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)
    sections = _split_headers(body, level=1)

    return Spec(
        id=frontmatter.get("id") or path.stem,
        service=frontmatter["service"],
        runs=int(frontmatter.get("runs", 1)),
        notes=sections.get("notes", "").strip(),
        quality_criteria=_parse_bullets(sections.get("quality_criteria", "")),
        settings=_parse_settings(sections.get("settings", "")),
        history=_parse_history(sections.get("history", "")),
        current_turn=_parse_role_content(sections.get("turn", ""), level=2),
        path=path,
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    frontmatter = yaml.safe_load(text[4:end]) or {}
    body = text[end + 4:].lstrip("\n")
    return frontmatter, body


def _split_headers(text: str, *, level: int) -> dict[str, str]:
    """Split markdown text into {name: content} on headers at the given level.

    Respects fenced code blocks — `#` lines inside ``` ... ``` are NOT treated as headers.
    """
    prefix = "#" * level + " "
    prefix_deeper = "#" * (level + 1)
    sections: dict[str, str] = {}
    current_name: Optional[str] = None
    current_lines: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current_lines.append(line)
            continue

        if (
            not in_fence
            and line.startswith(prefix)
            and not line.startswith(prefix_deeper + " ")
        ):
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).rstrip()
            current_name = line[len(prefix):].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).rstrip()
    return sections


def _parse_bullets(text: str) -> list[str]:
    bullets = []
    for line in text.splitlines():
        m = re.match(r"^- +(.*)$", line.rstrip())
        if m:
            bullets.append(m.group(1).strip())
    return bullets


def _parse_settings(text: str) -> dict[str, Any]:
    sub_sections = _split_headers(text, level=2)
    settings: dict[str, Any] = {}
    for key, value_text in sub_sections.items():
        _set_dotted(settings, key, _parse_value(value_text))
    return settings


def _parse_value(text: str) -> Any:
    text = text.strip()
    if not text:
        return ""

    fence = re.match(r"^```(\w*)\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        lang = fence.group(1).lower()
        content = fence.group(2)
        if lang == "json":
            return json.loads(content)
        return content

    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    return text


def _set_dotted(target: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = target
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _parse_history(text: str) -> list[dict[str, str]]:
    blocks = _split_repeated_header(text, level=2, name="turn")
    turns = []
    for block in blocks:
        turn = _parse_role_content(block, level=3)
        if turn:
            turns.append(turn)
    return turns


def _split_repeated_header(text: str, *, level: int, name: str) -> list[str]:
    """Split text on repeated headers like `## turn` (case-insensitive). Returns the
    body following each header, respecting fenced code blocks."""
    target = ("#" * level + " " + name).lower()
    blocks: list[str] = []
    current: list[str] = []
    started = False
    in_fence = False

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if started:
                current.append(line)
            continue

        if not in_fence and line.strip().lower() == target:
            if started:
                blocks.append("\n".join(current))
            current = []
            started = True
            continue

        if started:
            current.append(line)

    if started:
        blocks.append("\n".join(current))
    return blocks


def _parse_role_content(text: str, *, level: int) -> Optional[dict[str, str]]:
    if not text.strip():
        return None
    sub = _split_headers(text, level=level)
    role = sub.get("role", "").strip()
    content = sub.get("content", "").rstrip()
    if not role:
        return None
    return {"role": role, "content": content}
