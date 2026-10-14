"""The job guide rendered from `guidelines/rules/job/` must match the constant it replaced.

`snapshots/job_writing_summary.txt` is `prompt.py`'s `job_writing_summary` as it
was before the guide moved into `guidelines/`. Moving the text must not change a
byte of it: job_chat sets a prompt-cache breakpoint straight after the guide, and
any wording change belongs in its own measured PR, which updates this snapshot.
"""

from pathlib import Path

from job_chat import old_prompt, prompt

SNAPSHOT = Path(__file__).parent / "snapshots" / "job_writing_summary.txt"


def test_rendered_job_guide_is_byte_identical_to_the_snapshot() -> None:
    assert prompt.job_writing_summary == SNAPSHOT.read_text(encoding="utf-8")


def test_old_prompt_renders_the_same_guide() -> None:
    assert old_prompt.job_writing_summary == prompt.job_writing_summary
