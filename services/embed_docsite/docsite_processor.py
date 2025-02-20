import json
import os
import logging
import re
import requests
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DocsiteProcessor")

class DocsiteProcessor:
    def __init__(self, output_dir="./tmp/split_sections",
                 data_url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
        self.output_dir = output_dir
        self.data_url = data_url
        self.metadata_dict = None

    def fetch_data_from_url(self):
        """Fetches adaptor data from the adaptor docs url."""
        try:
            response = requests.get(self.data_url)
            response.raise_for_status()
            return response.json()
        
        except requests.RequestException as e:
            logger.error(f"Failed to fetch data: {e}")
            raise

    def write_chunks_to_file(self, chunks, file_name="adaptor_docs_chunks.json"):
        """
        Writes a list of documentation chunks to a JSON file in the specified directory.

        :param file_name: Name of the file to write to
        :param chunks: List of tuples (chunk, name) to write to the file
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

        # Write to a JSON file
        with open(output_file, 'w') as f:
            json.dump(chunks, f, indent=2)

        logger.info(f"Content written to {output_file}")

    def clean_html(self, text):
        """Remove HTML tags while preserving essential formatting."""
        text = re.sub(r'<\/?p>', '\n', text)  # Convert <p> to newlines
        text = re.sub(r'<\/?code>', '`', text)  # Convert <code> to backticks
        text = re.sub(r'<\/?strong>', '**', text)  # Convert <strong> to bold
        text = re.sub(r'<[^>]+>', '', text)  # Remove other HTML tags

        return text.strip()

    def split_by_headers(self, text):
        """Split text into chunks based on Markdown headers (# and ##)."""
        sections = re.split(r'(^#+\s.*)', text, flags=re.MULTILINE)  # Split by headers
        chunks = []
        current_chunk = ""

        for section in sections:
            if section.strip().startswith("#"):  # New section starts
                if current_chunk:
                    chunks.append(current_chunk.strip())  # Save previous chunk
                current_chunk = section.strip()  # Start new chunk
            else:
                current_chunk += "\n" + section.strip()  # Append content to current section

        if current_chunk:
            chunks.append(current_chunk.strip())  # Save last chunk

        return chunks

    def accumulate_chunks(self, chunks, target_length=1000):
        """Merge smaller chunks to get as close to target_length as possible."""
        accumulated = []
        current_chunk = ""
        
        for chunk in chunks:
            if len(current_chunk) + len(chunk) <= target_length or len(current_chunk) < target_length * 0.5:
                current_chunk += "\n\n" + chunk if current_chunk else chunk  # Append with spacing
            else:
                accumulated.append(current_chunk.strip())  # Store the completed chunk
                current_chunk = chunk  # Start a new chunk
        
        if current_chunk:
            accumulated.append(current_chunk.strip())  # Add any remaining text

        return accumulated

    def chunk_adaptor_docs(self, json_data, chunk_size=1000, min_chunk_size=100):
        """
        Extract docs from adaptor data, and chunk according to a target chunk size and a minimum chunk size.

        :param json_data: JSON containing adaptor data dictionaries and lists
        :return: List of tuples (chunk, adaptor name) and a dictionary with the original data {adaptor_name: data_dict}
        """
        output = []
        metadata_dict = dict()
        
        for item in json_data:
            if isinstance(item, dict) and "docs" in item and "name" in item:
                
                docs = item["docs"]#.strip().split("\n")
                name = item["name"]

                # Decode JSON string
                try:
                    docs = json.loads(docs)
                except json.JSONDecodeError:
                    pass
                
                docs = self.clean_html(docs)

                # Save all fields for adding to metadata later
                item["docs"] = docs # replace docs with cleaned text
                metadata_dict[name] = item

                # Chunk
                header_splits = self.split_by_headers(docs)
                chunks = self.accumulate_chunks(header_splits)

                for chunk in chunks:
                    output.append({"name": name, "doc_chunk": chunk})
        
        # self.metadata_dict = metadata_dict
        self.write_chunks_to_file(output)

        return output, metadata_dict      

    def get_preprocessed_docs(self):
        """Fetch and process adaptor data"""
        # Step 1: Fetch adaptor data
        adaptor_data = self.fetch_data_from_url()
        # Step 2: Process adaptor data
        chunks, metadata_dict = self.chunk_adaptor_docs(adaptor_data)

        #TODO get as langchain docs with metadata fields
        logger.info("Pipeline execution complete.")

        return chunks, metadata_dict