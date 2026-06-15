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
