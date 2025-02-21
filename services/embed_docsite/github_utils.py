import requests
from util import create_logger

logger = create_logger("GitHubUtils")

def download_main_docs(github_info):
    """Downloads and processes the main docs from GitHub API info."""
    output = []

    for file_info in github_info:
        try:
            response = requests.get(file_info["download_url"])
            response.raise_for_status()
            
            output.append({
                "name": file_info["name"],
                "docs": response.text
            })

        except requests.RequestException as e:
            logger.info(f"Failed to fetch content for {file_info['name']}: {e}")
    
    return output

def get_github_urls(repo, path="", owner="OpenFn", file_type=".md"):
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

def get_adaptor_function_docs(data_url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
    """Fetches adaptor data from the preprocessed adaptor docs url."""
    try:
        response = requests.get(data_url)
        response.raise_for_status()

        return response.json() 
    
    except requests.RequestException as e:
        logger.error(f"Failed to fetch data: {e}")

def get_github_path_contents(repo, path="", owner="OpenFn", file_type=".md"):
    """
    Get the contents of files from a GitHub repository.

    :param repo: The repository (e.g. "docs")
    :param path: The path from root (e.g. "")
    :param owner: The repository owner (default="OpenFn")
    :param file_type: File extension to filter by (default=".md")
    :return: List of dictionaries {name, docs}
    """
    # Get list of files
    github_files = get_github_urls(repo, path, owner, file_type)
    
    # Download and process each file
    files_data = download_main_docs(github_files)
            
    return files_data

def get_docs(docs_type):
    if docs_type == "adaptor_functions":
        return get_adaptor_function_docs()
    if docs_type == "general_docs":
        return get_github_path_contents(repo="docs", path="docs")
    if docs_type == "adaptor_docs": 
        return get_github_path_contents(repo="docs", path="adaptors")