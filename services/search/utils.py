import os
import glob
import logging
import requests
from pymilvus import MilvusClient,connections
from openai import OpenAI
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def connect_to_milvus() -> MilvusClient:
    """
    Connects to the Milvus database using environment variables.

    :return: MilvusClient instance
    :raises EnvironmentError: If required environment variables are not set
    """
    zilliz_uri = os.getenv('ZILLIZ_URI')
    zilliz_token = os.getenv('ZILLIZ_TOKEN')

    if not zilliz_uri or not zilliz_token:
        raise EnvironmentError("ZILLIZ_URI or ZILLIZ_TOKEN environment variables are not set.")

    logger.info(f"Connecting to Milvus database...")
    connections.connect("default", uri=zilliz_uri, token=zilliz_token, db_name="openfn_docs")

    return MilvusClient(uri=zilliz_uri, token=zilliz_token, db_name="openfn_docs")

def fetch_adaptor_data(url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
    """
    Fetches adaptor data from a given URL.

    :param url: URL to fetch JSON data from
    :return: Parsed JSON data
    :raises Exception: If the request fails
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch adaptor data: {e}")
        raise

def read_md_files(file_paths):
    """
    Reads content of markdown files from given file paths.

    :param file_paths: List of file paths to markdown files
    :return: List of tuples containing file path and file content
    """
    docs = []
    for file_path in file_paths:
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    docs.append((file_path, file.read()))
            except OSError as e:
                logger.error(f"Error reading file {file_path}: {e}")
        else:
            logger.warning(f"File {file_path} does not exist.")
    return docs

def read_paths_config(config_file, repo_path):
    """
    Reads file paths from a config file and resolves them using glob.

    :param config_file: Path to the configuration file containing file patterns
    :param repo_path: Base repository path to prepend to the file patterns
    :return: List of resolved file paths
    :raises FileNotFoundError: If the config file does not exist
    """
    if not os.path.isfile(config_file):
        raise FileNotFoundError(f"Configuration file {config_file} does not exist.")
    
    paths = []
    with open(config_file, 'r') as file:
        for line in file:
            pattern = line.strip()
            if pattern:
                full_pattern = os.path.expanduser(os.path.join(repo_path, pattern))
                logger.info(f"Processing pattern: {full_pattern}")
                matched_paths = glob.glob(full_pattern, recursive=True)
                
                if matched_paths:
                    paths.extend(matched_paths)
                else:
                    logger.warning(f"No matches found for pattern: {full_pattern}")
    return paths

def write_to_file(output_dir, file_name, content, header="## Section Start:\n"):
    """
    Writes content to a file in the specified directory.

    :param output_dir: Directory to store the output file
    :param file_name: Name of the file to write to
    :param content: Content to write to the file
    :param header: Optional header to prepend to each section of content
    """
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, file_name)
    
    with open(output_file, "w", encoding="utf-8") as out_file:
        for section in content:
            out_file.write(f"{header}\n{section}\n\n")
    logger.info(f"Content written to {output_file}")

def split_docs(file_name, content, output_dir="./tmp/split_sections"):
    """
    Splits markdown content into sections using headers and character count.

    :param file_name: Name of the file being split
    :param content: Content of the markdown file
    :param output_dir: Directory to store the split sections
    :return: List of split sections
    """
    headers_to_split_on = [("##", "Header 2"), ("###", "Header 3")]
    
    # Initialize splitters
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=256)

    # Split the document
    md_header_splits = markdown_splitter.split_text(content)
    splits = text_splitter.split_documents(md_header_splits)

    # Write the split sections to disk using the new write function
    file_name_with_extension = f"{os.path.basename(file_name)}_sections.md"
    write_to_file(output_dir, file_name_with_extension, [section.page_content for section in splits])

    return splits

def process_adaptor_data(adaptor_data, output_dir="./tmp/split_sections"):
    """
    Processes adaptor data to extract function details and generate documentation.

    :param adaptor_data: List of adaptors with function details
    :param output_dir: Directory to store the processed output
    :return: Tuple of corpus (list of chunks) and max_chunk_length
    """
    corpus = []
    function_data = []
    max_chunk_length = 0

    # Separate adaptors and functions
    for item in adaptor_data:
        if isinstance(item, dict) and 'adaptor' in item:
            # This is an adaptor
            adaptor_name = item['adaptor']
            functions = item['functions']
        elif isinstance(item, list):
            # This is the functions array
            function_data = [fn for fn in item if fn.get("kind") == "function"]
        else:
            continue

        for function in functions:
            for fn_detail in function_data:
                if fn_detail.get("name") == function:
                    description = fn_detail.get("description", "No description provided")
                    params = ", ".join([f"{p.get('name', 'No name provided')}: {p.get('description', 'No description provided')}" for p in fn_detail.get("params", [])])
                    examples = "; ".join(fn_detail.get("examples", []))
                        
                    # Create a chunk with a description                    
                    chunk = f"Adaptor: {adaptor_name} Function: {function} Description: {description} Parameters: {params} Examples: {examples}"
                    corpus.append(chunk)
                    
                    # Track max chunk length
                    max_chunk_length = max(max_chunk_length, len(chunk))
        
        function_data = []
    # Write the processed adaptor data to disk using the new write function
    write_to_file(output_dir, "adaptors.md", corpus)

    return corpus, max_chunk_length
