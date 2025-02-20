import json
import os
import logging
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

    def fetch_data(self):
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

        # Convert content to dictionaries
        json_data = [{"adaptor_name": name, "doc_chunk": chunk} for chunk, name in chunks]

        # Write to a JSON file
        with open(output_file, 'w') as f:
            json.dump(json_data, f, indent=2)

        logger.info(f"Content written to {output_file}")

    def chunk_adaptor_docs(self, json_data, chunk_size=1000, min_chunk_size=100):
        """
        Extract docs from adaptor data, and chunk according to a target chunk size and a minimum chunk size.

        :param json_data: JSON containing adaptor data dictionaries and lists
        :return: List of tuples (chunk, adaptor name) and a dictionary with the original data {adaptor_name: data_dict}
        """
        chunks = []
        metadata_dict = dict()
        
        for item in json_data:
            if isinstance(item, dict) and "docs" in item and "name" in item:
                docs = item["docs"].strip().split("\n")
                name = item["name"]
                chunk = ""

                # Save all fields for optional metadata addition
                metadata_dict[name] = item

                for line in docs:
                    if len(chunk) + len(line) + 1 > chunk_size:  
                        if len(chunk) >= min_chunk_size:
                            chunks.append((chunk.strip(), name))  
                        else:  
                            if chunks:  # Merge with the last chunk if possible – review if dealing with new data with sparse newlines
                                if chunks[-1][1] == name:
                                    last_chunk, last_name = chunks.pop()
                                    chunks.append((last_chunk + "\n" + chunk.strip(), last_name))
                        
                        chunk = ""

                    chunk += line + "\n"

                if chunk.strip():  # If there's remaining content
                    if len(chunk) >= min_chunk_size:
                        chunks.append((chunk.strip(), name))
                    elif chunks:  
                        last_chunk, last_name = chunks.pop()
                        chunks.append((last_chunk + "\n" + chunk.strip(), last_name))
        
        self.metadata_dict = metadata_dict
        self.write_chunks_to_file(chunks=chunks)

        return chunks, metadata_dict
        

    def get_preprocessed_docs(self):
        """Fetch and process adaptor data"""
        # Step 1: Fetch adaptor data
        adaptor_data = self.fetch_data()
        # Step 2: Process adaptor data
        chunks, metadata_dict = self.chunk_adaptor_docs(adaptor_data)

        #TODO get as langchain docs with metadata fields
        logger.info("Pipeline execution complete.")

        return chunks, metadata_dict