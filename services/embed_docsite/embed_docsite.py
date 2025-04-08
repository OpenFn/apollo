import os
import json
from dotenv import load_dotenv
import pandas as pd
from util import create_logger, ApolloError
from embed_docsite.docsite_processor import DocsiteProcessor
from embed_docsite.docsite_indexer import DocsiteIndexer

logger = create_logger("embed_docsite")

def main(data):
    logger.info("Starting...")

    # Get selection of doc types to upload, or default to all
    docs_to_upload = data.get("docs_to_upload", ["adaptor_docs", "general_docs", "adaptor_functions"])
    docs_to_ignore = data.get("docs_to_ignore", ["job-examples.md", "release-notes.md"])

    # Get other fields
    index_params = {}
    index_param_options = ["collection_name", "index_name", "max_total_collections"]

    for key in index_param_options:
        if key in data:
            index_params[key] = data[key]

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
    docsite_indexer = DocsiteIndexer(**(index_params or {}))

    # Add docs
    for docs_type in docs_to_upload:
        # Download and process
        docsite_processor = DocsiteProcessor(docs_type=docs_type, docs_to_ignore=docs_to_ignore)
        documents, metadata_dict = docsite_processor.get_preprocessed_docs()

        # Upload with metadata
        idx = docsite_indexer.insert_documents(documents, metadata_dict)

if __name__ == "__main__":
    main()