"""Langfuse tracking utilities for controlling trace export and tagging."""
import re
from typing import Any

_SECRET_KEY_NAMES = {"api_key", "anthropic_api_key", "authorization"}
_SECRET_VALUE_PATTERN = re.compile(r"sk-ant-[\w\-]+")


def mask_secrets(data: Any) -> Any:  # noqa: ANN401
    """Langfuse mask callback: redact API keys from all traced data.

    Applied by the SDK to every span's input, output and metadata before
    export, so keys passed as function arguments to @observe-decorated
    functions never reach Langfuse.
    """
    if isinstance(data, dict):
        return {
            k: "[REDACTED]" if str(k).lower() in _SECRET_KEY_NAMES and v else mask_secrets(v)
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [mask_secrets(v) for v in data]
    if isinstance(data, str):
        return _SECRET_VALUE_PATTERN.sub("[REDACTED]", data)
    return data


def should_track(data_dict: dict, force: bool = False) -> bool:
    """Check if this session should be tracked in Langfuse."""
    if force:
        return True
    return bool(data_dict.get("metrics_opt_in"))


def build_tags(service_name: str, user_info: dict) -> list:
    """Build Langfuse tags list from service name and user persona."""
    tags = [service_name]
    persona = user_info.get("persona") if user_info else None
    if persona:
        tags.append(persona)
    return tags
