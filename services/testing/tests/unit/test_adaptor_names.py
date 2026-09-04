from unittest.mock import patch

from testing import judge


def test_lists_real_adaptors_as_package_names():
    fake = [
        {"name": "redis", "version": "1.4.3", "description": "OpenFn adaptor for Redis"},
        {"name": "common", "version": "2.0.0", "description": "Common helpers"},
    ]
    with patch("workflow_chat.available_adaptors.get_available_adaptors", return_value=fake):
        names = judge.build_adaptor_names()

    assert names == "@openfn/language-common, @openfn/language-redis"


def test_fails_open_when_the_list_is_empty():
    # An empty list means the lookup failed, not that no adaptor exists. Passing
    # it on would have the judge flag every adaptor as invented.
    with patch("workflow_chat.available_adaptors.get_available_adaptors", return_value=[]):
        assert judge.build_adaptor_names() is None


def test_fails_open_when_the_lookup_raises():
    with patch(
        "workflow_chat.available_adaptors.get_available_adaptors",
        side_effect=RuntimeError("no network"),
    ):
        assert judge.build_adaptor_names() is None


def test_the_list_reaches_the_judge_prompt():
    prompt = judge._build_user_prompt(
        criteria=["something"],
        candidate={"response": "hi"},
        test_notes=None,
        request=None,
        adaptor_names="@openfn/language-redis",
    )

    assert "@openfn/language-redis" in prompt
    assert "Do not call a package invented when it appears here" in prompt


def test_no_adaptor_block_without_a_list():
    prompt = judge._build_user_prompt(
        criteria=["something"],
        candidate={"response": "hi"},
        test_notes=None,
        request=None,
    )

    assert "ADAPTOR PACKAGES" not in prompt


def test_evaluate_accepts_the_adaptor_list():
    import inspect

    assert "adaptor_names" in inspect.signature(judge.evaluate).parameters


def test_short_name_handles_every_adaptor_form():
    from workflow_chat.workflow_chat import AnthropicClient

    assert AnthropicClient.adaptor_short_name("@openfn/language-common@latest") == "common"
    assert AnthropicClient.adaptor_short_name("@openfn/language-common") == "common"
    assert AnthropicClient.adaptor_short_name("common@latest") == "common"
    assert AnthropicClient.adaptor_short_name("common") == "common"
    assert AnthropicClient.adaptor_short_name("@openfn/language-http@7.3.3") == "http"
    # A package outside the OpenFn scope resolves to nothing, so it is reported.
    assert AnthropicClient.adaptor_short_name("@foo/bar") == ""


def test_validation_is_skipped_when_the_adaptor_list_is_unavailable():
    # Otherwise a failed lookup reports every adaptor in the workflow as
    # invented, once per job, on every request until the cache warms.
    from workflow_chat.workflow_chat import AnthropicClient

    yaml_data = {"jobs": {"a": {"adaptor": "@openfn/language-common@latest"}}}
    with patch(
        "workflow_chat.workflow_chat.get_available_adaptors", return_value=[]
    ), patch("workflow_chat.workflow_chat.sentry_sdk") as sentry:
        AnthropicClient.validate_adaptors(None, yaml_data)

    sentry.push_scope.assert_not_called()
    sentry.capture_message.assert_not_called()
