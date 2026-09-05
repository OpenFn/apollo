"""Redaction has to hold back job code even when the document is odd.

Returning the original on failure hands the model the very bodies redaction
exists to withhold, and a YAML anchor can point at its own container, which
PyYAML builds as a real cycle.
"""

import pytest
import yaml
from workflow_chat.workflow_chat import AnthropicClient
from yaml_utils import WITHHELD_NOTICE, _remove_ids, redact_job_bodies

SECRET = "callSecretApi()"


def test_a_normal_workflow_is_still_redacted() -> None:
    out = redact_job_bodies(f"jobs:\n  a:\n    id: 123\n    body: {SECRET}\n")

    assert SECRET not in out
    assert "123" not in out
    assert "jobs" in out


@pytest.mark.parametrize(
    "document",
    [
        f'jobs: {{a: {{body: "{SECRET}"}}\n  broken',
        f"workflows:\n  wf:\n    jobs:\n      a:\n        body: {SECRET}\n",
        f"- {SECRET}\n",
        f"jobs: {SECRET}\n",
    ],
    ids=["unparseable", "jobs-nested-deeper", "a-list", "jobs-not-a-mapping"],
)
def test_a_document_it_cannot_redact_is_withheld(document: str) -> None:
    out = redact_job_bodies(document)

    assert SECRET not in out
    assert out == WITHHELD_NOTICE


def test_the_id_walk_terminates_on_a_self_referential_anchor() -> None:
    data = yaml.safe_load("jobs:\n  a: &x\n    body: code()\n    loop: *x\n")
    assert data["jobs"]["a"]["loop"] is data["jobs"]["a"]

    _remove_ids(data)

    assert "id" not in data["jobs"]["a"]


def test_redaction_terminates_on_a_self_referential_anchor() -> None:
    out = redact_job_bodies(f"jobs:\n  a: &x\n    body: {SECRET}\n    loop: *x\n")

    assert SECRET not in out


@pytest.mark.parametrize(
    "yaml_data",
    [
        {"jobs": [{"body": "code()"}]},
        {"jobs": {"a": {"body": 42}}},
        {"jobs": {"a": None}},
        {"jobs": "not a mapping"},
        {"triggers": {"t": None}},
        {"edges": {"e": "not a mapping"}},
    ],
    ids=["jobs-a-list", "numeric-body", "null-job", "jobs-a-string",
         "null-trigger", "edge-not-a-mapping"],
)
def test_preserving_components_tolerates_a_shape_it_did_not_expect(yaml_data: dict) -> None:
    preserved, _ = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert isinstance(preserved, dict)
