import os

from dotenv import load_dotenv
from embed_docsite.docsite_cache import refresh_cache
from util import ApolloError, create_logger

logger = create_logger("embed_docsite")

def main(data):
    logger.info("Starting...")

    # Get selection of doc types to upload, or default to all
    docs_to_upload = data.get("docs_to_upload", ["adaptor_docs", "general_docs", "adaptor_functions"])
    docs_to_ignore = data.get("docs_to_ignore", ["job-examples.md", "release-notes.md"])

    if data.get("refresh_cache_only"):
        logger.info("Refreshing the docs cache only")
        return {"target": "cache", **refresh_cache(docs_to_upload)}

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

    # Imported here, not at module scope: DocsiteIndexer builds an
    # OpenAIEmbeddings() default argument at class-definition time (so importing
    # it demands OPENAI_API_KEY), DocsiteProcessor runs nltk.download() at
    # import, and both pull in pandas. A refresh_cache_only run must pay none of
    # that.
    from embed_docsite.docsite_indexer import DocsiteIndexer  # noqa: PLC0415 - see comment above
    from embed_docsite.docsite_processor import DocsiteProcessor  # noqa: PLC0415 - see comment above

    # One refresh for the whole run: the markdown refresh covers every markdown
    # docs_type in a single conditional Trees request. Ahead of the indexer, so a
    # fatal fetch failure leaves no empty collection behind. Each
    # DocsiteProcessor below then reads from disk.
    refresh_cache(docs_to_upload)

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