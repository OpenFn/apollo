import requests
from typing import List, Tuple
from langchain_text_splitters import RecursiveCharacterTextSplitter
from util import create_logger, ApolloError

logger = create_logger("DocProcessor")


class DocProcessor:
    def __init__(self, chunk_size=512, chunk_overlap=50):
        self.text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            encoding_name="cl100k_base",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def process_document(self, doc_url: str) -> Tuple[str, List[str]]:
        text, doc_title = self._fetch_document(doc_url)
        chunks = self._chunk_text(text)
        return doc_title, chunks

    def _fetch_document(self, url: str) -> Tuple[str, str]:
        try:
            logger.info(f"Fetching document from {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()

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
        chunks = self.text_splitter.split_text(text)
        logger.info(f"Created {len(chunks)} chunks")
        return chunks
