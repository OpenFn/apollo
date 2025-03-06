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

    # Parse payload
    # Get required fields
    required_fields = ["collection_name"]
    missing = [field for field in required_fields if field not in data]
    
    if missing:
        logger.error(f"Missing required fields in data: {', '.join(missing)}")
        return
    
    collection_name = data["collection_name"]

    # Get selection of doc types to upload, or default to all
    docs_to_upload = data.get("docs_to_upload", ["adaptor_docs", "general_docs", "adaptor_functions"])

    # Get other fields
    other_params = {}
    other_param_options = ["index_name"]

    for key in other_param_options:
        if key in data:
            other_params[key] = data[key]

    # Set API keys
    load_dotenv(override=True)

    if data.get("PINECONE_API_KEY", ""):
        PINECONE_API_KEY = data["PINECONE_API_KEY"]
    else:
        PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
    
    if data.get("OPENAI_API_KEY", ""):
        OPENAI_API_KEY = data["OPENAI_API_KEY"]
    else:
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    
    # Check for missing keys
    missing_keys = []

    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY") 
    if not PINECONE_API_KEY:
        missing_keys.append("PINECONE_API_KEY")

    if missing_keys:
        msg = f'Missing API keys: {", ".join(missing_keys)}'
        logger.error(msg)
        raise ApolloError(500, f'Missing API keys: {", ".join(missing_keys)}. Add to payload or environment.', type="BAD_REQUEST")

    # Initialize indexer
    docsite_indexer = DocsiteIndexer(collection_name=collection_name, **other_params)

    # Add docs
    for docs_type in docs_to_upload:
        # Download and process
        docsite_processor = DocsiteProcessor(docs_type=docs_type)
        documents, metadata_dict = docsite_processor.get_preprocessed_docs()

        # Upload with metadata
        idx = docsite_indexer.insert_documents(documents, metadata_dict)

if __name__ == "__main__":
    main()