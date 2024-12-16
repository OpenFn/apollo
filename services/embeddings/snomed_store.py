import os
from dotenv import load_dotenv
from embeddings.embeddings import VectorStore

def connect_snomed():
    """Initialise the vector store for SNOMED embeddings."""

    load_dotenv()

    store = VectorStore(
        collection_name="snomed-mappings",
        index_name="apollo-mappings",
        vectorstore_type="pinecone",
        embedding_type="openai"
    )

    return store