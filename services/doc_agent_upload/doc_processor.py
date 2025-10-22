import requests
import re
from typing import List, Tuple
from util import create_logger, ApolloError

logger = create_logger("DocProcessor")


class DocProcessor:
    def __init__(self, target_length=1000, min_length=700, overlap=150):
        self.target_length = target_length
        self.min_length = min_length
        self.overlap = overlap

    def process_document(self, doc_url: str) -> Tuple[str, List[str]]:
        """
        Fetch document from URL and chunk it.
        Returns: (doc_title, list_of_chunks)
        """
        text, doc_title = self._fetch_document(doc_url)
        chunks = self._chunk_text(text)
        return doc_title, chunks

    def _fetch_document(self, url: str) -> Tuple[str, str]:
        """Fetch document text from URL."""
        try:
            logger.info(f"Fetching document from {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Extract title from URL (simple heuristic)
            doc_title = url.split('/')[-1].replace('.txt', '').replace('.md', '')
            if not doc_title:
                doc_title = "Untitled Document"

            text = response.text
            logger.info(f"Fetched {len(text)} characters")
            return text, doc_title

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch document: {str(e)}")
            raise ApolloError(400, f"Failed to fetch document: {str(e)}", type="FETCH_ERROR")

    def _chunk_text(self, text: str) -> List[str]:
        """
        Simple overlapped chunking strategy:
        1. Split by paragraphs
        2. Accumulate to target length
        3. Add overlap between chunks
        """
        # Split into paragraphs
        paragraphs = re.split(r'\n\s*\n', text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_chunk = ""
        overlap_text = ""

        for para in paragraphs:
            # If adding this paragraph keeps us under target, add it
            if len(current_chunk) + len(para) + 1 <= self.target_length:
                if current_chunk:
                    current_chunk += "\n\n"
                current_chunk += para
            else:
                # Current chunk is ready
                if len(current_chunk) >= self.min_length:
                    chunks.append(current_chunk)
                    # Save overlap from end of chunk
                    overlap_text = self._get_overlap(current_chunk)
                    current_chunk = overlap_text + "\n\n" + para if overlap_text else para
                else:
                    # Chunk too small, keep accumulating
                    if current_chunk:
                        current_chunk += "\n\n"
                    current_chunk += para

        # Add final chunk
        if current_chunk:
            if len(current_chunk) >= self.min_length or len(chunks) == 0:
                chunks.append(current_chunk)
            else:
                # Merge small final chunk with last chunk
                if chunks:
                    chunks[-1] = chunks[-1] + "\n\n" + current_chunk
                else:
                    chunks.append(current_chunk)

        logger.info(f"Created {len(chunks)} chunks")
        return chunks

    def _get_overlap(self, text: str) -> str:
        """Get overlap text from end of chunk (last N characters)."""
        if len(text) <= self.overlap:
            return text
        return text[-self.overlap:]
