"""Langfuse tracking utilities for controlling trace export and tagging."""


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
