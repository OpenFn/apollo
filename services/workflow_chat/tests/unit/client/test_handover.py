"""Unit tests for subagent-mode handover parsing in workflow_chat."""

import json

from workflow_chat.workflow_chat import AnthropicClient


def make_client() -> AnthropicClient:
    """Build an AnthropicClient without an API key."""
    client = AnthropicClient.__new__(AnthropicClient)
    client._streamed_yaml = None
    client._handover = None
    return client


def test_split_captures_handover_and_skips_yaml() -> None:
    client = make_client()
    response = json.dumps({"handover": "asks about job code", "yaml": "name: wf", "text": ""})

    text, output_yaml = client.split_format_yaml(response)

    assert client._handover == "asks about job code"
    assert output_yaml == ""
    assert text == ""


def test_split_without_handover_behaves_normally() -> None:
    client = make_client()
    response = json.dumps({"handover": None, "yaml": None, "text": "The trigger runs daily."})

    text, output_yaml = client.split_format_yaml(response)

    assert client._handover is None
    assert text == "The trigger runs daily."
    assert output_yaml == ""


def test_split_legacy_schema_without_handover_field() -> None:
    client = make_client()
    response = json.dumps({"yaml": None, "text": "Answer."})

    text, _ = client.split_format_yaml(response)

    assert client._handover is None
    assert text == "Answer."
