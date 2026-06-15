"""
Central Claude model configuration.
Update values here to change models used across all services.
"""

import os

CLAUDE_MODELS: dict[str, str] = {
    "claude-opus":   "claude-opus-4-8",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-haiku":  "claude-haiku-4-5-20251001",
}

CLAUDE_OPUS:   str = CLAUDE_MODELS["claude-opus"]
CLAUDE_SONNET: str = CLAUDE_MODELS["claude-sonnet"]
CLAUDE_HAIKU:  str = CLAUDE_MODELS["claude-haiku"]


def resolve_model(alias: str) -> str:
    """Resolve a model alias to its full ID. Passes through unknown strings unchanged."""
    return CLAUDE_MODELS.get(alias, alias)


# --- Main chat model selection ----------------------------------------------
#
# The "main chat model" is the large model that drives user-facing chat
# (job_chat, workflow_chat, doc_agent_chat, and the global_chat planner). It is
# distinct from the smaller models used for RAG/routing (haiku/sonnet), which
# are configured directly and are NOT affected by the helper below.

# Env var that overrides the main chat model at runtime, so we can switch the
# live model without a redeploy. Holds a model alias or full ID.
CHAT_MODEL_ENV = "APOLLO_CHAT_MODEL"

# Default main chat model when neither the env var nor a service config overrides it.
CHAT_MODEL_DEFAULT = CLAUDE_OPUS


def preferred_chat_model(config_value: str | None = None) -> str:
    """Resolve the main chat model.

    Precedence: APOLLO_CHAT_MODEL env var > per-service config value > CLAUDE_OPUS.
    The env var lets us switch the live chat model without redeploying.
    """
    override = os.getenv(CHAT_MODEL_ENV)
    if override:
        return resolve_model(override)
    if config_value:
        return resolve_model(config_value)
    return CHAT_MODEL_DEFAULT
