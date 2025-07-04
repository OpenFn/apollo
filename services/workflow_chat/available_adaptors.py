import os
import json
import time
from latest_adaptors.latest_adaptors import get_latest_adaptors
from util import create_logger

logger = create_logger("workflow_chat/available_adaptors")

ADAPTORS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "adaptors_cache.json")
CACHE_TTL_SECONDS = 3600  # 1 hour

def is_cache_fresh(path, ttl_seconds):
    """Return True if the cache file exists and is not older than ttl_seconds."""
    if not os.path.exists(path):
        return False
    mtime = os.path.getmtime(path)
    age = time.time() - mtime
    return age < ttl_seconds

def get_available_adaptors():
    """Returns a list of available adaptors (dicts with name, version, description), using a recent cache or the adaptor service."""
    if is_cache_fresh(ADAPTORS_CACHE_PATH, CACHE_TTL_SECONDS):
        with open(ADAPTORS_CACHE_PATH, "r") as f:
            return json.load(f)
    else:
        try:
            adaptors_info = get_latest_adaptors()
            # adaptors_info is a dict mapping name to info
            adaptors_list = [
                {"name": name, **info}
                for name, info in adaptors_info.items()
                if info is not None
            ]
            with open(ADAPTORS_CACHE_PATH, "w") as f:
                json.dump(adaptors_list, f)
            return adaptors_list
        except Exception:
            logger.warning(f"Get latest adaptors failed, using cache")
            if os.path.exists(ADAPTORS_CACHE_PATH):
                with open(ADAPTORS_CACHE_PATH, "r") as f:
                    return json.load(f)
            return []

def get_adaptors_string():
    available_adaptors = get_available_adaptors()
    adaptors_string = ""
    for adaptor in available_adaptors:
        full_name = f"{adaptor['name']}@{adaptor['version']}"
        adaptors_string += f"{full_name}: {adaptor['description']}\n"
    return adaptors_string