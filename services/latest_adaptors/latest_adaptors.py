import requests
from util import create_logger

logger = create_logger("latest_adaptors")

def get_latest_adaptors():
    # Get all adaptor names
    packages_url = "https://api.github.com/repos/OpenFn/adaptors/contents/packages"
    logger.info(f'Fetching adaptor list fom {packages_url}')

    response = requests.get(packages_url)
    response.raise_for_status()
    
    package_dirs = response.json()
    package_names = [item['name'] for item in package_dirs if item['type'] == 'dir']
    
    # Get descriptions
    descriptions = {}
    for package_name in package_names:
        try:
            raw_url = f"https://raw.githubusercontent.com/OpenFn/adaptors/main/packages/{package_name}/package.json"
            logger.info(f'fetching {raw_url}')
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

def main(args) -> dict:
    adaptor_info = get_latest_adaptors()
    #logger.info(adaptor_info)
    return adaptor_info

if __name__ == "__main__":
    main()