import os
from dotenv import load_dotenv
from embeddings.embeddings import VectorStore

def connect_loinc(api_key):
    """Initialise the vector store for LOINC embeddings."""

    load_dotenv()

    store = VectorStore(
        collection_name="loinc-mappings-v2",
        index_name="apollo-mappings",
        vectorstore_type="pinecone",
        embedding_type="openai",
        api_key=api_key
    )

    return store