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

# Global override env var. When set, forces every chat service to this model
# (except a service that has its own env var set — see precedence below).
CHAT_MODEL_ENV = "APOLLO_CHAT_MODEL"

# Per-service model config. `default` is the built-in choice; `env`, if set at
# runtime, overrides it (and the global env var) for that service only.
# Services not listed use CHAT_MODEL_DEFAULT and only honour CHAT_MODEL_ENV.
CHAT_SERVICE_MODELS: dict[str, dict[str, str]] = {
    # workflow_chat forces JSON/YAML output via structured outputs; Sonnet
    # handles that better than Opus today, so it defaults to Sonnet.
    "workflow_chat": {"default": CLAUDE_SONNET, "env": "APOLLO_WORKFLOW_CHAT_MODEL"},
    "job_chat":      {"default": CLAUDE_OPUS,   "env": "APOLLO_JOB_CHAT_MODEL"},
}


def preferred_chat_model(service: str | None = None) -> str:
    """Resolve the main chat model for `service`.

    Precedence (most specific wins):
        per-service env var  >  global env var (APOLLO_CHAT_MODEL)
                             >  per-service default  >  CHAT_MODEL_DEFAULT

    So APOLLO_CHAT_MODEL is a "force everything" switch, while a per-service env
    var (e.g. APOLLO_WORKFLOW_CHAT_MODEL) pins that one service against it. All
    env vars are optional; with none set, each service uses its default. The env
    vars let us switch the live model without redeploying.
    """
    cfg = CHAT_SERVICE_MODELS.get(service, {})

    service_override = os.getenv(cfg["env"]) if cfg.get("env") else None
    if service_override:
        return resolve_model(service_override)

    global_override = os.getenv(CHAT_MODEL_ENV)
    if global_override:
        return resolve_model(global_override)

    return cfg.get("default", CHAT_MODEL_DEFAULT)
