import os
import glob
import logging
import requests
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DocsiteProcessor")

class DocsiteProcessor:
    def __init__(self, repo_path, config_file, output_dir="./tmp/split_sections",
                 data_url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
        self.repo_path = repo_path
        self.config_file = config_file
        self.output_dir = output_dir
        self.data_url = data_url

    def fetch_data(self):
        """Fetches adaptor data from the adaptor docs url."""
        try:
            response = requests.get(self.data_url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch data: {e}")
            raise

    def read_md_files(self, file_paths):
        """Reads content of markdown files from given file paths."""
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

    def read_paths_config(self):
        """
        Reads file paths from a config file and resolves them using glob.

        :return: List of resolved file paths
        :raises FileNotFoundError: If the config file does not exist
        """
        if not os.path.isfile(self.config_file):
            raise FileNotFoundError(f"Configuration file {self.config_file} does not exist.")

        paths = []
        with open(self.config_file, 'r') as file:
            for line in file:
                pattern = line.strip()
                if pattern:
                    full_pattern = os.path.expanduser(os.path.join(self.repo_path, pattern))
                    logger.info(f"Processing pattern: {full_pattern}")
                    matched_paths = glob.glob(full_pattern, recursive=True)

                    if matched_paths:
                        paths.extend(matched_paths)
                    else:
                        logger.warning(f"No matches found for pattern: {full_pattern}")
        return paths

    def write_to_file(self, file_name, content, header="## Section Start:\n"):
        """
        Writes content to a file in the specified directory.

        :param file_name: Name of the file to write to
        :param content: Content to write to the file
        :param header: Optional header to prepend to each section of content
        """
        os.makedirs(self.output_dir, exist_ok=True)
        output_file = os.path.join(self.output_dir, file_name)
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                print(f"Existing output file '{output_file}' has been deleted.")
            except OSError as e:
                print(f"Error deleting the file {output_file}: {e}")
                return

        with open(output_file, "w", encoding="utf-8") as out_file:
            for section in content:
                out_file.write(f"{header}\n{section}\n\n")
        logger.info(f"Content written to {output_file}")

    def split_docs(self, file_name, content):
        """
        Splits markdown content into sections using headers and character count.

        :param file_name: Name of the file being split
        :param content: Content of the markdown file
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
        self.write_to_file(file_name_with_extension, [section.page_content for section in splits])
        
        return splits

    def process_adaptor_data(self, adaptor_data):
        """
        Processes adaptor data to extract function details and generate documentation.

        :param adaptor_data: List of adaptors with function details
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
                        params = ", ".join([
                            f"{p.get('name', 'No name provided')}: {p.get('description', 'No description provided')}"
                            for p in fn_detail.get("params", [])
                        ])
                        examples = "; ".join(fn_detail.get("examples", []))
                        
                        # Create a chunk with a description
                        chunk = (f"Adaptor: {adaptor_name} Function: {function} "
                                 f"Description: {description} Parameters: {params} Examples: {examples}")
                        corpus.append(chunk)
                        
                        # Track max chunk length
                        max_chunk_length = max(max_chunk_length, len(chunk))
                
                function_data = []
        
        # Write the processed adaptor data to disk using the new write function
        self.write_to_file("adaptors.md", corpus)
        
        return corpus, max_chunk_length

    def get_preprocessed_docs(self):
        """Fetch and process adaptor data"""
        # Step 1: Fetch adaptor data
        adaptor_data = self.fetch_data()
        # Step 2: Process adaptor data
        corpus, max_chunk_length = self.process_adaptor_data(adaptor_data)

        #TODO get as langchain docs with metadata fields
        logger.info("Pipeline execution complete.")

        return corpus, max_chunk_length