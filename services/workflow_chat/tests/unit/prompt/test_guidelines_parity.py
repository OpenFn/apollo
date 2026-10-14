"""The general-knowledge prompt must render the same bytes after its rules moved into `guidelines/`.

`snapshots/general_knowledge.txt` is the `general_knowledge` template from
`prompts.yaml` as it was before the trigger, job and edge rules moved into
`guidelines/rules/workflow/`. Formatted with the same adaptor list and name rule,
it must match today's render exactly. A wording change belongs in its own
measured PR, which updates this snapshot.
"""

from pathlib import Path

import pytest
from name_rules import UNICODE_FLAG_ENV, describe_rule_for_prompt
from workflow_chat import prompt
from workflow_chat.available_adaptors import get_adaptors_string

SNAPSHOT = Path(__file__).parent / "snapshots" / "general_knowledge.txt"


@pytest.mark.parametrize("unicode_names", ["false", "true"])
def test_general_knowledge_is_byte_identical_to_the_snapshot(
    monkeypatch: pytest.MonkeyPatch, unicode_names: str,
) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, unicode_names)

    expected = SNAPSHOT.read_text(encoding="utf-8").format(
        adaptors=get_adaptors_string(),
        name_rule=describe_rule_for_prompt(),
    )

    assert prompt._general_knowledge() == expected
