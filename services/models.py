"""
Central Claude model configuration.
Update values here to change models used across all services.
"""

import os
from collections.abc import Callable
from typing import Any

import anthropic

CLAUDE_MODELS: dict[str, str] = {
    "claude-opus":      "claude-opus-4-8",
    "claude-opus-prev": "claude-opus-4-7",
    "claude-sonnet":    "claude-sonnet-4-6",
    "claude-haiku":     "claude-haiku-4-5-20251001",
}

CLAUDE_OPUS:      str = CLAUDE_MODELS["claude-opus"]
CLAUDE_OPUS_PREV: str = CLAUDE_MODELS["claude-opus-prev"]
CLAUDE_SONNET:    str = CLAUDE_MODELS["claude-sonnet"]
CLAUDE_HAIKU:     str = CLAUDE_MODELS["claude-haiku"]


def resolve_model(alias: str) -> str:
    """Resolve a model alias to its full ID. Passes through unknown strings unchanged."""
    return CLAUDE_MODELS.get(alias, alias)


# --- Main chat model selection ----------------------------------------------
#
# The "main chat model" is the large model that drives user-facing chat
# (job_chat, workflow_chat, doc_agent_chat, and the global_chat planner). It is
# distinct from the smaller models used for RAG/routing (haiku/sonnet), which
# are configured directly and are NOT affected by the helpers below.
#
# The whole per-service model story lives here on purpose, so there is one place
# to read what each service uses and how to override it. Nothing is configured
# in the service yamls.

# Default chat model for any service without its own entry below.
CHAT_MODEL_DEFAULT = CLAUDE_OPUS

# Per-service model config. `default` is the built-in choice; `env`, if set at
# runtime, overrides it for that service only (one env var per service, no
# global override). Services not listed (e.g. doc_agent_chat) use
# CHAT_MODEL_DEFAULT and have no runtime override.
CHAT_SERVICE_MODELS: dict[str, dict[str, str]] = {
    # workflow_chat forces JSON/YAML output via structured outputs; Sonnet
    # handles that better than Opus today, so it defaults to Sonnet.
    "workflow_chat": {"default": CLAUDE_SONNET, "env": "APOLLO_WORKFLOW_CHAT_MODEL"},
    "job_chat":      {"default": CLAUDE_OPUS,   "env": "APOLLO_JOB_CHAT_MODEL"},
    "global_chat":   {"default": CLAUDE_OPUS,   "env": "APOLLO_GLOBAL_CHAT_MODEL"},
}


def preferred_chat_model(service: str | None = None) -> str:
    """Resolve the main chat model for `service`.

    Precedence: the service's env var if set, else its per-service default, else
    CHAT_MODEL_DEFAULT. Each service's env var (e.g. APOLLO_WORKFLOW_CHAT_MODEL)
    is optional and lets us switch that one service's live model without
    redeploying.
    """
    cfg = CHAT_SERVICE_MODELS.get(service, {})

    env_name = cfg.get("env")
    if env_name:
        override = os.getenv(env_name)
        if override:
            return resolve_model(override)

    return cfg.get("default", CHAT_MODEL_DEFAULT)


# --- Fallback when the preferred model is unavailable ------------------------
#
# When a chat call's preferred model is unavailable, we try the next model in
# this chain rather than failing the request. The preferred model is tried
# first; this chain provides the ordered fallbacks after it.
CHAT_FALLBACK_CHAIN: list[str] = [CLAUDE_OPUS, CLAUDE_OPUS_PREV, CLAUDE_SONNET]

# HTTP status codes that mean "the provider/model is down or overloaded right
# now" and we should try the next model: 500 (api_error), 502/503 (gateway/
# unavailable), 529 (overloaded). The SDK already retries these with backoff
# before they surface here, so reaching this point means retries were exhausted.
# (The SDK version in use has no dedicated OverloadedError class — 529 arrives
# as a plain APIStatusError — so we classify by status code.)
_MODEL_DOWN_STATUS_CODES = frozenset({500, 502, 503, 529})


def chat_model_chain(preferred: str | None = None) -> list[str]:
    """Ordered models to try for a main-chat call: the preferred model first,
    then the fallback chain, de-duplicated while preserving order."""
    first = preferred or preferred_chat_model()
    return list(dict.fromkeys([first, *CHAT_FALLBACK_CHAIN]))


def _fallback_steps(preferred: str | None) -> list[tuple[str, str | None]]:
    """The chain as (model, next_model) pairs; next_model is None for the last
    model, which is what tells the fallback loops "no more models to try"."""
    models = chat_model_chain(preferred)
    return list(zip(models, [*models[1:], None], strict=True))


def is_model_unavailable_error(exc: BaseException) -> bool:
    """True if `exc` means the model itself is unavailable and we should fall
    back to the next model rather than surfacing the error.

    Covers a removed/renamed model (404 not_found — permanent, not retried by
    the SDK) and a down/overloaded provider (500/502/503/529 — transient,
    surfaced only after the SDK's own retries are exhausted).
    """
    if isinstance(exc, anthropic.NotFoundError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return getattr(exc, "status_code", None) in _MODEL_DOWN_STATUS_CODES
    return False


def _alert_model_fallback(failed_model: str, next_model: str, exc: BaseException) -> None:
    """Flag a fallback to Sentry. A fallback is meant to be temporary — it keeps
    chat up, but someone should fix the preferred model (or the env override) soon."""
    msg = (
        f"Chat model {failed_model!r} unavailable ({type(exc).__name__}); "
        f"falling back to {next_model!r}"
    )
    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.capture_message(msg, level="warning")
    except Exception:
        pass
    # Also surface in private logs (print, not the client-facing logger).
    print(msg)  # noqa: T201


def call_with_model_fallback(attempt: Callable[[str], Any], *, preferred: str | None = None) -> Any:  # noqa: ANN401
    """Run `attempt(model)` against the chat model chain, advancing to the next
    model only on model-unavailable errors. Returns `attempt`'s result; re-raises
    the original error for non-fallback errors or once the chain is exhausted.

    For non-streaming calls. For streaming, use `stream_with_model_fallback`.
    """
    for model, next_model in _fallback_steps(preferred):
        try:
            return attempt(model)
        except Exception as exc:
            if next_model is None or not is_model_unavailable_error(exc):
                raise
            _alert_model_fallback(model, next_model, exc)


def stream_with_model_fallback(
    open_stream: Callable[[str], Any],
    consume: Callable[..., Any],
    *,
    preferred: str | None = None,
) -> Any:  # noqa: ANN401
    """Streaming counterpart of `call_with_model_fallback`.

    Args:
        open_stream: `open_stream(model)` -> the result of `client.messages.stream(...)`
            (a context manager, not yet entered).
        consume: `consume(stream_obj, commit)` -> processes events and returns a
            result. Call `commit()` as soon as any user-facing content has been
            sent; after that a failure re-raises instead of falling back, so we
            never re-stream a partial answer to the user.

    Fallback only happens for failures at stream-open / before the first
    committed content (the case where a removed or overloaded model surfaces).
    """
    for model, next_model in _fallback_steps(preferred):
        committed = False

        def commit() -> None:
            nonlocal committed
            committed = True

        try:
            with open_stream(model) as stream_obj:
                return consume(stream_obj, commit)
        except Exception as exc:
            if committed or next_model is None or not is_model_unavailable_error(exc):
                raise
            _alert_model_fallback(model, next_model, exc)
