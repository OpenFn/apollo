import requests

def get_all_adaptor_descriptions():
    # Get all adaptor names
    packages_url = "https://api.github.com/repos/OpenFn/adaptors/contents/packages"
    response = requests.get(packages_url)
    response.raise_for_status()
    
    package_dirs = response.json()
    package_names = [item['name'] for item in package_dirs if item['type'] == 'dir']
    
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
            print(f"Failed to fetch {package_name}: {e}")
            descriptions[package_name] = None
    
    return descriptions