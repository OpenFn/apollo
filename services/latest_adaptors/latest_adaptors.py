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

def get_latest_adaptors():
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
            logger.error(f"Failed to fetch {package_name}: {e}")
            descriptions[package_name] = None
    
    logger.info('All adaptor metadata downloaded')

    return descriptions

def get_latest_adaptors_cached():
    """Returns a dict of latest adaptors, using a recent cache or the adaptor service."""
    if is_cache_fresh(ADAPTORS_CACHE_PATH, CACHE_TTL_SECONDS):
        with open(ADAPTORS_CACHE_PATH, "r") as f:
            return json.load(f)
    else:
        try:
            adaptors_info = get_latest_adaptors()
            with open(ADAPTORS_CACHE_PATH, "w") as f:
                json.dump(adaptors_info, f)
            return adaptors_info
        except Exception:
            logger.warning(f"Get latest adaptors failed, using cache")
            if os.path.exists(ADAPTORS_CACHE_PATH):
                with open(ADAPTORS_CACHE_PATH, "r") as f:
                    return json.load(f)
            return {}

def main(args) -> dict:
    adaptor_info = get_latest_adaptors()
    #logger.info(adaptor_info)
    return adaptor_info

if __name__ == "__main__":
    main()