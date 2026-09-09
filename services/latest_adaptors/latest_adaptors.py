import requests
import os
import json
import time
from util import create_logger

logger = create_logger("latest_adaptors")

ADAPTORS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "adaptors_cache.json")
CACHE_TTL_SECONDS = 3600  # 1 hour

IGNORED_ADAPTORS = [
    "devtools",
    "template",
    "fhir-jembi",
    "collections",
]

def is_cache_fresh(path, ttl_seconds):
    """Return True if the cache file exists and is not older than ttl_seconds."""
    if not os.path.exists(path):
        return False
    mtime = os.path.getmtime(path)
    age = time.time() - mtime
    return age < ttl_seconds

def get_latest_adaptors(previous: dict | None = None) -> dict:
    """Fetch latest adaptor metadata from GitHub.

    If a per-adaptor fetch fails (e.g. rate limiting), fall back to that
    adaptor's entry in the previous cache rather than dropping it.
    """
    previous = previous or {}

    # Get all adaptor names
    packages_url = "https://api.github.com/repos/OpenFn/adaptors/contents/packages"
    logger.info(f'Fetching adaptor list fom {packages_url}')

    response = requests.get(packages_url)
    response.raise_for_status()

    package_dirs = response.json()
    package_names = [item['name'] for item in package_dirs if item['type'] == 'dir']
    # Filter out ignored adaptors (case-insensitive)
    ignored = set(name.lower() for name in IGNORED_ADAPTORS)
    package_names = [name for name in package_names if name.lower() not in ignored]

    # Get descriptions
    descriptions = {}
    for package_name in package_names:
        try:
            raw_url = f"https://raw.githubusercontent.com/OpenFn/adaptors/main/packages/{package_name}/package.json"
            pkg_response = requests.get(raw_url)
            pkg_response.raise_for_status()
            package_json = pkg_response.json()
            descriptions[package_name] = {
                'description': package_json.get('description', ''),
                'label': package_json.get('label', ''),
                'version': package_json.get('version', '')
            }
        except Exception as e:
            old_entry = previous.get(package_name)
            if old_entry is not None:
                logger.warning(f"Failed to fetch {package_name}, keeping cached entry: {e}")
                descriptions[package_name] = old_entry
            else:
                logger.error(f"Failed to fetch {package_name} and no cached entry: {e}")

    logger.info('All adaptor metadata downloaded')

    return descriptions

def load_cache() -> dict | None:
    """Return the cached adaptors dict (dropping empty entries), or None if unreadable."""
    if not os.path.exists(ADAPTORS_CACHE_PATH):
        return None
    try:
        with open(ADAPTORS_CACHE_PATH) as f:
            data = json.load(f)
        return {name: info for name, info in data.items() if info is not None}
    except Exception as e:
        logger.warning(f"Failed to read adaptors cache: {e}")
        return None


def write_cache(adaptors_info: dict) -> None:
    """Atomically write the adaptors cache so readers never see a partial file."""
    tmp_path = f"{ADAPTORS_CACHE_PATH}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(adaptors_info, f)
    os.replace(tmp_path, ADAPTORS_CACHE_PATH)


def get_latest_adaptors_cached() -> dict:
    """Returns a dict of latest adaptors, using a recent cache or the adaptor service."""
    cached = load_cache()
    if cached is not None and is_cache_fresh(ADAPTORS_CACHE_PATH, CACHE_TTL_SECONDS):
        return cached
    try:
        adaptors_info = get_latest_adaptors(previous=cached)
        write_cache(adaptors_info)
        return adaptors_info
    except Exception:
        logger.warning("Get latest adaptors failed, using cache")
        return cached if cached is not None else {}

def main(args) -> dict:
    adaptor_info = get_latest_adaptors()
    #logger.info(adaptor_info)
    return adaptor_info

if __name__ == "__main__":
    main()