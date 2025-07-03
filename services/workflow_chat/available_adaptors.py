
import os
import json
import time
from ..latest_adaptors.latest_adaptors import get_latest_adaptors

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
    """Returns a dict of available adaptors, using a recent cache or the adaptor service."""
    if is_cache_fresh(ADAPTORS_CACHE_PATH, CACHE_TTL_SECONDS):
        with open(ADAPTORS_CACHE_PATH, "r") as f:
            return json.load(f)
    else:
        try:
            adaptors_info = get_latest_adaptors()
            adaptors_info = adaptors_info["adaptors"]
            adaptors_info = {adaptor["name"]: adaptor["description"] for adaptor in adaptors_info}
            with open(ADAPTORS_CACHE_PATH, "w") as f:
                json.dump(adaptors_info, f)
            return adaptors_info
        except Exception:
            if os.path.exists(ADAPTORS_CACHE_PATH):
                with open(ADAPTORS_CACHE_PATH, "r") as f:
                    return json.load(f)
            return {}

def get_adaptors_string():
    available_adaptors = get_available_adaptors()
    adaptors_string = ""
    for key, value in available_adaptors.items():
        adaptors_string += f"{key}: {value}\n"
    return adaptors_string