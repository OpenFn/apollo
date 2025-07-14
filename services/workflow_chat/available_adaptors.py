import os
import json
import time
from latest_adaptors.latest_adaptors import get_latest_adaptors_cached
from util import create_logger

logger = create_logger("workflow_chat/available_adaptors")

def get_available_adaptors():
    """Returns a list of available adaptors (dicts with name, version, description), using a recent cache or the adaptor service."""
    try:
        adaptors_info = get_latest_adaptors_cached()
        adaptors_list = [
            {"name": name, **info}
            for name, info in adaptors_info.items()
            if info is not None
        ]
        return adaptors_list
    except Exception:
        logger.warning(f"Get latest adaptors failed, returning empty list")
        return []

def get_adaptors_string():
    available_adaptors = get_available_adaptors()
    adaptors_string = ""
    for adaptor in available_adaptors:
        full_name = f"{adaptor['name']}@{adaptor['version']}"
        adaptors_string += f"{full_name}: {adaptor['description']}\n"
    return adaptors_string