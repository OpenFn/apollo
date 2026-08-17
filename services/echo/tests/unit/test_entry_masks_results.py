"""The boundary every service result passes through.

Services are handed a payload with values the server put there, and whatever
they return goes back to the caller. Rather than trust each one not to reflect
those values, `entry.call` masks on the way out.

Driven through `_masking_probe`, which reflects its payload and masks nothing
itself, so these fail if the boundary stops working. Pointing them at `echo`
would prove only that echo masks.
"""

import json

import pytest
from entry import call

HTTP_INTERNAL_ERROR = 500


@pytest.fixture
def input_file(tmp_path: object) -> object:
    def write(payload: dict) -> str:
        path = tmp_path / "input.json"
        path.write_text(json.dumps(payload))
        return str(path)

    return write


def test_masks_a_server_set_field_in_the_result(input_file: object) -> None:
    result = call(
        "_masking_probe",
        input_path=input_file({"api_key": "secret", "x": 1}),
    )

    assert result["api_key"] == "[REDACTED]"
    assert result["x"] == 1


def test_masks_a_key_shaped_value_anywhere_in_the_result(input_file: object) -> None:
    result = call(
        "_masking_probe",
        input_path=input_file({"note": "configured with sk-ant-abc123"}),
    )

    assert "sk-ant-abc123" not in json.dumps(result)


def test_masks_a_key_that_reached_an_error_message(input_file: object) -> None:
    # A service that raises with the payload in scope is the common shape:
    # most catch broadly and rewrap as ApolloError(500, str(e)).
    result = call(
        "_masking_probe_raiser",
        input_path=input_file({"api_key": "sk-ant-abc123"}),
    )

    assert result["code"] == HTTP_INTERNAL_ERROR
    assert "sk-ant-abc123" not in json.dumps(result)
