import uuid

from workflow_chat.workflow_chat import AnthropicClient


def _restore(yaml_data, preserved):
    # restore_components does not touch `self`; calling it unbound keeps the
    # test off the constructor, which wants an API key.
    AnthropicClient.restore_components(None, yaml_data, preserved)


def test_trigger_id_survives_the_round_trip():
    trigger_id = str(uuid.uuid4())
    yaml_data = {"triggers": {"webhook": {"id": trigger_id, "type": "webhook"}}}

    preserved, _ = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert "id" not in yaml_data["triggers"]["webhook"]

    _restore(yaml_data, preserved)

    assert yaml_data["triggers"]["webhook"]["id"] == trigger_id


def test_trigger_id_survives_the_model_renaming_the_trigger():
    trigger_id = str(uuid.uuid4())
    yaml_data = {"triggers": {"webhook": {"id": trigger_id, "type": "webhook"}}}

    preserved, _ = AnthropicClient.extract_and_preserve_components(yaml_data)

    returned = {
        "triggers": {"cron": {"type": "cron", "cron_expression": "0 0 * * *"}}
    }
    _restore(returned, preserved)

    assert returned["triggers"]["cron"]["id"] == trigger_id


def test_a_new_trigger_gets_an_id():
    returned = {"triggers": {"webhook": {"type": "webhook"}}}

    _restore(returned, {})

    assert uuid.UUID(returned["triggers"]["webhook"]["id"])


def test_custom_path_reaches_the_model_untouched():
    yaml_data = {
        "triggers": {
            "webhook": {
                "id": str(uuid.uuid4()),
                "type": "webhook",
                "custom_path": "et-emr-facility-001",
            }
        }
    }

    _, processed = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert "custom_path: et-emr-facility-001" in processed
