"""
Central Claude model configuration.
Update values here to change models used across all services.
"""

CLAUDE_MODELS: dict[str, str] = {
    "claude-opus":   "claude-opus-5-5",
    "claude-sonnet": "claude-sonnet-5-5",
    "claude-haiku":  "claude-haiku-5-5",
}

CLAUDE_OPUS:   str = CLAUDE_MODELS["claude-opus"]
CLAUDE_SONNET: str = CLAUDE_MODELS["claude-sonnet"]
CLAUDE_HAIKU:  str = CLAUDE_MODELS["claude-haiku"]

# These models think when `thinking` is omitted, where the 4.x ones didn't.
# Calls that never thought pass these to keep it off. Each is model-specific:
# Sonnet 5.5 rejects "disabled", and only Sonnet 5.5 accepts "between_tools".
NO_THINKING_HAIKU:  dict = {"type": "disabled"}
NO_THINKING_SONNET: dict = {"type": "between_tools"}


def resolve_model(alias: str) -> str:
    """Resolve a model alias to its full ID. Passes through unknown strings unchanged."""
    return CLAUDE_MODELS.get(alias, alias)
