"""Unit tests for the central chat-model selection and fallback logic in
`services/models.py`.

No real model calls: errors are fabricated anthropic exception instances and the
work is done by fake `attempt` / stream callables. The repo-root conftest marks
everything under a `unit/` dir as `unit` and blocks real client construction, so
these stay fast and offline.
"""

import anthropic
import models as m
import pytest

_WORKFLOW_ENV = m.CHAT_SERVICE_MODELS["workflow_chat"]["env"]


# --- helpers ----------------------------------------------------------------

def _not_found() -> anthropic.NotFoundError:
    """A 404 NotFoundError without going through the HTTP-bound __init__."""
    return anthropic.NotFoundError.__new__(anthropic.NotFoundError)


def _status_error(code: int) -> anthropic.APIStatusError:
    """An APIStatusError carrying `code`, without a real HTTP response."""
    exc = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    exc.status_code = code
    return exc


class FakeStreamCM:
    """Stands in for the context manager `client.messages.stream(...)` returns.

    Raises `open_error` on __enter__ (mimicking a model-unavailable error at
    stream open) and records whether it was entered/exited so tests can assert
    the `with` block was cleaned up.
    """

    def __init__(self, *, open_error: BaseException | None = None) -> None:
        self.open_error = open_error
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        if self.open_error is not None:
            raise self.open_error
        return self

    def __exit__(self, *_exc: object) -> bool:
        self.exited = True
        return False


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Clear all per-service overrides so the real environment can't skew tests."""
    for cfg in m.CHAT_SERVICE_MODELS.values():
        monkeypatch.delenv(cfg["env"], raising=False)


# --- preferred_chat_model: defaults + precedence ----------------------------

def test_unlisted_service_uses_default():
    # A service with no entry (e.g. doc_agent_chat, or none at all) uses the default.
    assert m.preferred_chat_model() == m.CHAT_MODEL_DEFAULT
    assert m.preferred_chat_model("doc_agent_chat") == m.CHAT_MODEL_DEFAULT


def test_per_service_defaults():
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_SONNET
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS
    assert m.preferred_chat_model("global_chat") == m.CLAUDE_OPUS


def test_env_var_overrides_its_service_default(monkeypatch):
    # Also proves the env value is alias-resolved ("claude-opus" -> full ID).
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-opus")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_OPUS


def test_env_var_is_scoped_to_one_service(monkeypatch):
    # Setting one service's var must not affect another service.
    monkeypatch.setenv(_WORKFLOW_ENV, "claude-haiku")
    assert m.preferred_chat_model("workflow_chat") == m.CLAUDE_HAIKU
    assert m.preferred_chat_model("job_chat") == m.CLAUDE_OPUS  # unaffected


# --- chat_model_chain: order + dedup ----------------------------------------

def test_chain_default_order():
    assert m.chat_model_chain() == [m.CLAUDE_OPUS, m.CLAUDE_OPUS_PREV, m.CLAUDE_SONNET]


def test_chain_dedupes_when_preferred_already_in_chain():
    # sonnet is already in the fallback chain; it should appear once, first.
    assert m.chat_model_chain(m.CLAUDE_SONNET) == [
        m.CLAUDE_SONNET,
        m.CLAUDE_OPUS,
        m.CLAUDE_OPUS_PREV,
    ]


def test_chain_prepends_a_novel_preferred_model():
    chain = m.chat_model_chain("claude-haiku-4-5-20251001")
    assert chain[0] == "claude-haiku-4-5-20251001"
    assert chain[1:] == m.CHAT_FALLBACK_CHAIN


# --- is_model_unavailable_error: which errors trigger fallback --------------

def test_not_found_is_unavailable():
    # 404: model removed/renamed (e.g. a model that was taken down).
    assert m.is_model_unavailable_error(_not_found()) is True


@pytest.mark.parametrize("code", [500, 502, 503, 529])
def test_provider_down_codes_are_unavailable(code):
    assert m.is_model_unavailable_error(_status_error(code)) is True


# 400 = generic client error; 429 = rate limit, the important "do NOT fall back"
# case (a busy account isn't a reason to switch models).
@pytest.mark.parametrize("code", [400, 429])
def test_other_status_codes_are_not_unavailable(code):
    assert m.is_model_unavailable_error(_status_error(code)) is False


def test_connection_and_generic_errors_are_not_unavailable():
    # A network blip is not model-specific; falling back to another model won't help.
    conn = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    assert m.is_model_unavailable_error(conn) is False
    assert m.is_model_unavailable_error(ValueError("nope")) is False


# --- call_with_model_fallback (non-streaming) -------------------------------

def test_call_returns_first_model_result_without_fallback(monkeypatch):
    alerts = []
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: alerts.append(a))
    tried = []

    def attempt(model):
        tried.append(model)
        return f"ok:{model}"

    assert m.call_with_model_fallback(attempt) == f"ok:{m.CLAUDE_OPUS}"
    assert tried == [m.CLAUDE_OPUS]
    assert alerts == []  # no fallback => no alert


def test_call_falls_back_on_404_and_alerts(monkeypatch):
    alerts = []
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: alerts.append(a))
    tried = []

    def attempt(model):
        tried.append(model)
        if model == m.CLAUDE_OPUS:
            raise _not_found()
        return f"ok:{model}"

    assert m.call_with_model_fallback(attempt) == f"ok:{m.CLAUDE_OPUS_PREV}"
    assert tried == [m.CLAUDE_OPUS, m.CLAUDE_OPUS_PREV]
    # one alert, naming the failed and next model
    assert len(alerts) == 1
    failed, nxt, _exc = alerts[0]
    assert (failed, nxt) == (m.CLAUDE_OPUS, m.CLAUDE_OPUS_PREV)


def test_call_does_not_fall_back_on_non_model_error(monkeypatch):
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    tried = []

    def attempt(model):
        tried.append(model)
        raise _status_error(400)

    with pytest.raises(anthropic.APIStatusError):
        m.call_with_model_fallback(attempt)
    assert tried == [m.CLAUDE_OPUS]  # propagated immediately, no fallback


def test_call_raises_last_error_when_whole_chain_down(monkeypatch):
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    tried = []

    def attempt(model):
        tried.append(model)
        raise _status_error(529)

    with pytest.raises(anthropic.APIStatusError) as excinfo:
        m.call_with_model_fallback(attempt)
    assert excinfo.value.status_code == 529
    assert tried == m.chat_model_chain()  # every model attempted


def test_call_respects_preferred_model(monkeypatch):
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    tried = []

    def attempt(model):
        tried.append(model)
        return model

    assert m.call_with_model_fallback(attempt, preferred=m.CLAUDE_SONNET) == m.CLAUDE_SONNET
    assert tried == [m.CLAUDE_SONNET]


# --- stream_with_model_fallback ---------------------------------------------

def test_stream_falls_back_when_open_fails(monkeypatch):
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    opened = []
    cms = {}

    def open_stream(model):
        opened.append(model)
        cm = FakeStreamCM(open_error=_not_found() if model == m.CLAUDE_OPUS else None)
        cms[model] = cm
        return cm

    def consume(stream, commit):
        commit()
        return f"streamed:{stream}"

    result = m.stream_with_model_fallback(open_stream, consume, preferred=m.CLAUDE_OPUS)
    assert opened == [m.CLAUDE_OPUS, m.CLAUDE_OPUS_PREV]
    assert result.startswith("streamed:")
    # __enter__ raising means the `with` never calls __exit__ on the failed CM
    # (standard context-manager semantics); the model that opened successfully
    # is the one that gets exited cleanly.
    assert cms[m.CLAUDE_OPUS].entered is True
    assert cms[m.CLAUDE_OPUS].exited is False
    assert cms[m.CLAUDE_OPUS_PREV].exited is True


def test_stream_does_not_fall_back_after_commit(monkeypatch):
    # Once user-facing content is sent, a later model-unavailable error must NOT
    # trigger a fallback (we won't re-stream a partial answer).
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    opened = []

    def open_stream(model):
        opened.append(model)
        return FakeStreamCM()

    def consume(stream, commit):
        commit()  # we've shown the user something
        raise _status_error(529)  # ...then the model dies mid-stream

    with pytest.raises(anthropic.APIStatusError):
        m.stream_with_model_fallback(open_stream, consume, preferred=m.CLAUDE_OPUS)
    assert opened == [m.CLAUDE_OPUS]  # no second model tried


def test_stream_falls_back_on_pre_commit_consume_failure(monkeypatch):
    # Failure during consume but before any content was committed is still safe
    # to fall back on.
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    opened = []

    def open_stream(model):
        opened.append(model)
        return FakeStreamCM()

    def consume(stream, commit):
        if opened[-1] == m.CLAUDE_OPUS:
            raise _status_error(503)  # before commit()
        commit()
        return "ok"

    assert m.stream_with_model_fallback(open_stream, consume, preferred=m.CLAUDE_OPUS) == "ok"
    assert opened == [m.CLAUDE_OPUS, m.CLAUDE_OPUS_PREV]


def test_stream_does_not_fall_back_on_non_model_error(monkeypatch):
    monkeypatch.setattr(m, "_alert_model_fallback", lambda *a: None)
    opened = []

    def open_stream(model):
        opened.append(model)
        return FakeStreamCM(open_error=_status_error(400))

    def consume(stream, commit):  # pragma: no cover - never reached
        commit()
        return "ok"

    with pytest.raises(anthropic.APIStatusError):
        m.stream_with_model_fallback(open_stream, consume)
    assert opened == [m.CLAUDE_OPUS]
