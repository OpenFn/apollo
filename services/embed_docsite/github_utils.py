import requests
from util import create_logger

logger = create_logger("GithubUtils")

def download_and_process(file_info):
    try:
        response = requests.get(file_info["download_url"])
        response.raise_for_status()
        
        return {
            "name": file_info["name"],
            "docs": response.text
        }
    except requests.RequestException as e:
        logger.error(f"Failed to fetch content for {file_info['name']}: {e}")
        return None


def get_github_files(repo, path="", owner="OpenFn", file_type=".md"):
    """"
    Get the download URLs for a GitHub repository.

    :param repo: The repository (e.g. "docs")
    :param path: The path from root (e.g. "")
    :param owner: The repository owner (default="OpenFn")
    :return: List of dictionaries {name, path, download_url}
    """
    files = []
    
    def fetch_contents(current_path):
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{current_path}"
        response = requests.get(url)
        contents = response.json()
        
        # Handle single file response
        if not isinstance(contents, list):
            contents = [contents]
            
        for item in contents:
            if item["type"] == "file" and item["name"].endswith(file_type):
                files.append({
                    "name": item["name"],
                    "path": item["path"],
                    "download_url": item["download_url"]
                })
            elif item["type"] == "dir":
                fetch_contents(item["path"])
    
    fetch_contents(path)

    return files

def get_github_file_contents(repo, path="", owner="OpenFn", file_type=".md"):
    """
    Get the contents of files from a GitHub repository.

    :param repo: The repository (e.g. "docs")
    :param path: The path from root (e.g. "")
    :param owner: The repository owner (default="OpenFn")
    :param file_type: File extension to filter by (default=".md")
    :return: List of dictionaries {name, docs}
    """
    # Get list of files
    github_files = get_github_files(repo, path, owner, file_type)
    
    # Download and process each file
    files_data = []
    for file_info in github_files:
        result = download_and_process(file_info)
        if result:
            files_data.append(result)
            
    return files_data

