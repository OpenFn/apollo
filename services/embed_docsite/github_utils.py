import requests
from embed_docsite.docs_repo import read_markdown_docs, sync_docs_repo
from util import create_logger

logger = create_logger("GitHubUtils")

def get_adaptor_function_docs(data_url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
    """Fetches adaptor data from the preprocessed adaptor docs url."""
    try:
        response = requests.get(data_url)
        response.raise_for_status()

        return response.json() 
    
    except requests.RequestException as e:
        logger.error(f"Failed to fetch data: {e}")

def get_docs(docs_type):
    if docs_type == "adaptor_functions":
        return get_adaptor_function_docs()
    sync_docs_repo()
    return read_markdown_docs(docs_type)