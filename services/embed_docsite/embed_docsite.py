import os
import time
from datetime import datetime
import json
from dotenv import load_dotenv
import pandas as pd
from util import create_logger, ApolloError
from embed_docsite.docsite_processor import DocsiteProcessor
from embed_docsite.docsite_indexer import DocsiteIndexer

logger = create_logger("embed_docsite")

def main(data):
    logger.info("Starting...")

    required_fields = ["docs_to_upload", "collection_name"]
    missing = [field for field in required_fields if field not in data]
    
    if missing:
        logger.error(f"Missing required fields in data: {', '.join(missing)}")
        return
    
    DOCS_TO_UPLOAD = data["docs_to_upload"]
    COLLECTION_NAME = data["collection_name"]

    # Set API keys
    load_dotenv(override=True)
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")

    # Check for missing keys
    missing_keys = []

    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY") 
    if not PINECONE_API_KEY:
        missing_keys.append("PINECONE_API_KEY")

    if missing_keys:
        msg = f'Missing API keys: {", ".join(missing_keys)}'
        logger.error(msg)
        raise ApolloError(500, f'Missing API keys: {", ".join(missing_keys)}', type="BAD_REQUEST")

    # Initialize indexer
    docsite_indexer = DocsiteIndexer(collection_name=COLLECTION_NAME)

    # Add docs
    for docs_type in DOCS_TO_UPLOAD:
        # Download and process
        docsite_processor = DocsiteProcessor(docs_type=docs_type)
        documents, metadata_dict = docsite_processor.get_preprocessed_docs()
        print(len(documents))

        # Upload with metadata
        documents = documents[:5] #TODO remove
        docsite_indexer.insert_documents(documents, metadata_dict)
    
    logger.info(f"Uploaded docs to Pinecone index {COLLECTION_NAME}")

if __name__ == "__main__":
    main()