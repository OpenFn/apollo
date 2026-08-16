"""Boundaries of the shared mask.

`mask_secrets` is both the Langfuse export mask and what stops a service
handing a key back to its caller, so it has to catch keys without eating the
workflow YAML, job code and prose it also passes over.
"""

import pytest

from langfuse_util import mask_secrets

KEY_SHAPED = [
    "sk-ant-abc123",
    "sk-ant-api03-Zm9vYmFy_baz",
    "sk-proj-0123456789abcdef",
    "use sk-ant-abc123 to authenticate",
    "(sk-ant-abc123)",
]

# Every one of these ends in a token the pattern used to bite through: task-,
# risk-, disk-, mask-, kiosk-.
ORDINARY_TEXT = [
    "task-scheduler-configuration",
    "risk-assessment-framework",
    "disk-usage-monitoring-job",
    "mask-generation-pipeline",
    "kiosk-registration-workflow-id",
    "https://docs.openfn.org/build/task-automation-guide",
    "const task = 'task-runner-config-value';",
]


@pytest.mark.parametrize("text", KEY_SHAPED)
def test_masks_a_key_shaped_value(text: str) -> None:
    assert "[REDACTED]" in mask_secrets(text)


@pytest.mark.parametrize("text", ORDINARY_TEXT)
def test_leaves_ordinary_text_alone(text: str) -> None:
    assert mask_secrets(text) == text


def test_masks_by_field_name_whatever_the_value_looks_like() -> None:
    masked = mask_secrets({"api_key": "not-key-shaped", "message": "hello"})

    assert masked["api_key"] == "[REDACTED]"
    assert masked["message"] == "hello"


def test_keeps_the_langfuse_public_key() -> None:
    # Public by design, and useful in a trace for telling which project a span
    # was bound for.
    masked = mask_secrets({"langfuse_public_key": "pk-lf-123"})

    assert masked["langfuse_public_key"] == "pk-lf-123"


def test_masks_nested_and_listed_values() -> None:
    masked = mask_secrets({"outer": [{"api_key": "sk-ant-abc123"}]})

    assert masked["outer"][0]["api_key"] == "[REDACTED]"
