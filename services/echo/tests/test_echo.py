import pytest
from echo.echo import main
from util import ApolloError


def test_echoes_the_payload_back() -> None:
    assert main({"message": "hello"}) == {"message": "hello"}


def test_rejects_an_empty_payload() -> None:
    with pytest.raises(ApolloError):
        main({})

    with pytest.raises(ApolloError):
        main({"session_id": "abc"})


def test_does_not_return_server_set_fields() -> None:
    # The server sets these itself, so their values must not come back out.
    echoed = main({"message": "hello", "api_key": "test-value"})

    assert "test-value" not in str(echoed)
    assert echoed["message"] == "hello"


def test_masks_a_key_shaped_value_anywhere_in_the_payload() -> None:
    echoed = main({"note": "config uses sk-ant-abc123 for now"})

    assert "sk-ant-abc123" not in str(echoed)
