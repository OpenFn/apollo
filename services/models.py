"""
Central Claude model configuration.
Update values here to change models used across all services.
"""

CLAUDE_MODELS: dict[str, str] = {
    "claude-opus":   "claude-opus-4-8",
    # Fable rejects temperature/top_p/top_k and any explicit `thinking`
    # config other than {"type": "adaptive"}; tokenizer yields ~30% more
    # tokens than Sonnet/Opus for the same content.
    "claude-fable":  "claude-fable-5",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-haiku":  "claude-haiku-4-5-20251001",
}

CLAUDE_OPUS:   str = CLAUDE_MODELS["claude-opus"]
CLAUDE_FABLE:  str = CLAUDE_MODELS["claude-fable"]
CLAUDE_SONNET: str = CLAUDE_MODELS["claude-sonnet"]
CLAUDE_HAIKU:  str = CLAUDE_MODELS["claude-haiku"]


def resolve_model(alias: str) -> str:
    """Resolve a model alias to its full ID. Passes through unknown strings unchanged."""
    return CLAUDE_MODELS.get(alias, alias)
