"""Unit tests for the global_chat request payload."""

from global_chat.global_chat import Payload


def test_web_search_defaults_to_off_when_options_are_absent() -> None:
    assert Payload.from_dict({"content": "hi"}).get_web_search() is False


def test_web_search_defaults_to_off_when_options_omit_the_key() -> None:
    assert Payload.from_dict({"content": "hi", "options": {"stream": True}}).get_web_search() is False


def test_web_search_is_read_from_options() -> None:
    payload = Payload.from_dict({"content": "hi", "options": {"web_search": True}})

    assert payload.get_web_search() is True
