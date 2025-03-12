import json
import os
import logging
import re
import requests
import nltk
from embed_docsite.github_utils import get_docs
from util import create_logger, ApolloError

nltk.download('punkt_tab')

logger = create_logger("DocsiteProcessor")

class DocsiteProcessor:
    """
    Processes documentation sites by cleaning, splitting, and chunking text.

    :param docs_type: Type of documentation being processed ("adaptor_functions", "general_docs", "adaptor_docs")
    :param output_dir: Directory to store processed chunks (default: "./tmp/split_sections").
    """
    def __init__(self, docs_type, docs_to_ignore=["job-examples.md", "release-notes.md"], output_dir="./tmp/split_sections"):
        self.output_dir = output_dir
        self.docs_type = docs_type
        self.docs_to_ignore = docs_to_ignore
        self.metadata_dict = None

    def get_preprocessed_docs(self):
        """
        Fetch, clean and chunk adaptor data.
        
        :return: List of chunk dictionaries {name, docs_type, doc_chunk}, and a dictionary mapping 
        adaptor_name to original data dictionary
        """
        # Step 1: Download docs
        docs = get_docs(docs_type=self.docs_type)

        # Step 2: Process adaptor data
        chunks, metadata_dict = self._chunk_adaptor_docs(docs)

        logger.info(f"{self.docs_type} docs preprocessed and chunked")

        return chunks, metadata_dict

    def _chunk_adaptor_docs(self, json_data, target_length=1000, overlap=1, min_length=700):
        """Extract and clean docs from adaptor data, and chunk according to a target and minimum chunk sizes."""
        output = []
        metadata_dict = dict()
        
        for item in json_data:
            if isinstance(item, dict) and "docs" in item and "name" in item:
                if item["name"] in self.docs_to_ignore:
                    continue
                
                docs = item["docs"]
                name = item["name"]

                # Decode JSON string
                try:
                    docs = json.loads(docs)
                except json.JSONDecodeError:
                    pass
                
                docs = self._clean_html(docs)

                # Save all fields for adding to metadata later
                item["docs"] = docs # replace docs with cleaned text
                metadata_dict[name] = item

                # Split by headers, and where needed, sentences
                splits = self._split_by_headers(docs)
                splits = self._split_oversized_chunks(chunks=splits, target_length=target_length)
                chunks = self._accumulate_chunks(splits=splits, target_length=target_length, overlap=overlap, min_length=min_length)

                for chunk in chunks:
                    output.append({"name": name, "docs_type": self.docs_type, "doc_chunk": chunk})
        
        # self.metadata_dict = metadata_dict
        self._write_chunks_to_file(chunks=output, file_name=f"{self.docs_type}_chunks.json")

        return output, metadata_dict      

    def _clean_html(self, text):
        """Remove HTML tags while preserving essential formatting."""
        text = re.sub(r'<\/?p>', '\n', text)  # Convert <p> to newlines
        text = re.sub(r'<\/?code>', '`', text)  # Convert <code> to backticks
        text = re.sub(r'<\/?strong>', '**', text)  # Convert <strong> to bold
        text = re.sub(r'<[^>]+>', '', text)  # Remove other HTML tags

        return text.strip()

    def _split_by_headers(self, text):
        """Split text into chunks based on Markdown headers (# and ##) and code blocks."""
        sections = re.split(r'(?=^#+\s.*$|^```(?:.*\n[\s\S]*?^```))', text, flags=re.MULTILINE)

        return [chunk.strip() for chunk in sections if chunk.strip()]

    def _split_oversized_chunks(self, chunks, target_length):
        """Check if chunks are over the target lengths, and split them further if needed."""
        result = []
        
        for chunk in chunks:
            if len(chunk) <= target_length:
                result.append(chunk)
            else:
                # Chunk is too big, split by newlines
                lines = chunk.split('\n')
                current_chunk = ""
                
                for line in lines:
                    # If adding this line would exceed target size and we already have content
                    if len(current_chunk) + len(line) + 1 > target_length and current_chunk:
                        result.append(current_chunk)
                        current_chunk = line
                    else:
                        # Add a newline if the chunk isn't empty
                        if current_chunk:
                            current_chunk += '\n'
                        current_chunk += line
                
                # Add the last chunk
                if current_chunk:
                    result.append(current_chunk)
        
        return result

    def _accumulate_chunks(self, splits, target_length, overlap, min_length):
        """Merge smaller chunks to get as close to target_length as possible."""
        accumulated = []
        current_chunk = ""
        last_overlap_length = 0
        
        for split in splits:
            if len(current_chunk) + len(split) <= target_length:
                current_chunk += split
            else:
                if len(current_chunk) >= min_length:
                    accumulated.append(current_chunk)  # Store the completed chunk

                    # add overlap
                    if self.docs_type == "adaptor_functions":
                        overlap_sections = " ".join(current_chunk.split("\n")[-overlap:])
                    else:
                        overlap_sections = " ".join(nltk.sent_tokenize(current_chunk)[-overlap:]) # Split by sentences (doesn't split code)
                    current_chunk = overlap_sections + split  # Start a new chunk
                    last_overlap_length = len(overlap_sections)
                else:
                    # Current chunk is too small, add the next split even though it exceeds target_length
                    current_chunk += split
        
        if current_chunk:
            if len(current_chunk) >= min_length or len(accumulated)==0:
                accumulated.append(current_chunk)
            else:
                current_chunk = current_chunk[last_overlap_length:] # Avoid duplication inside one chunk
                filler_char = min_length - len(current_chunk)
                if len(accumulated[-1]) > filler_char:
                    filler_overlap = accumulated[-1][-filler_char:]
                    accumulated.append(filler_overlap + current_chunk)
                else:
                    accumulated[-1] = accumulated[-1] + current_chunk

        return accumulated

    def _write_chunks_to_file(self, chunks, file_name):
        """Writes a list of documentation chunks to a JSON file in the specified directory."""
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