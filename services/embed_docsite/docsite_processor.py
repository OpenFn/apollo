import json
import os
import logging
import re
import requests
from embed_docsite.github_utils import get_docs
from util import create_logger, ApolloError

logger = create_logger("DocsiteProcessor")

class DocsiteProcessor:
    """
    Processes documentation sites by cleaning, splitting, and chunking text.

    :param docs_type: Type of documentation being processed ("adaptor_functions", "general_docs", "adaptor_docs")
    :param output_dir: Directory to store processed chunks (default: "./tmp/split_sections").
    """
    def __init__(self, docs_type, output_dir="./tmp/split_sections"):
        self.output_dir = output_dir
        self.docs_type = docs_type
        self.metadata_dict = None

    def write_chunks_to_file(self, chunks, file_name):
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
                logger.info(f"Existing output file '{output_file}' has been deleted.")
            except OSError as e:
                logger.error(f"Error deleting the file {output_file}: {e}")

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
        """Split text into chunks based on Markdown headers (# and ##) and code blocks."""
        sections = re.split(r'(?=^#+\s.*$|^```(?:.*\n[\s\S]*?^```))', text, flags=re.MULTILINE)

        return [chunk.strip() for chunk in sections if chunk.strip()]

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
                
                docs = item["docs"]
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
                    output.append({"name": name, "docs_type": self.docs_type, "doc_chunk": chunk})
        
        # self.metadata_dict = metadata_dict
        self.write_chunks_to_file(chunks=output, file_name=f"{self.docs_type}_chunks.json")

        return output, metadata_dict      

    def get_preprocessed_docs(self):
        """Fetch and process adaptor data"""
        # Step 1: Download docs
        docs = get_docs(docs_type=self.docs_type)

        # Step 2: Process adaptor data
        chunks, metadata_dict = self.chunk_adaptor_docs(docs)

        logger.info(f"{self.docs_type} docs preprocessed and chunked")

        return chunks, metadata_dict