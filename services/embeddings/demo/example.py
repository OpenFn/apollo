import os
from dotenv import load_dotenv
from embeddings.embeddings import VectorStore

def get_demo_vectorstore():
    """Initialise the vector store instance to be used by the embeddings_demo service."""

    load_dotenv()

    store = VectorStore(
        collection_name="demo_project",
        vectorstore_type="zilliz",
        embedding_type="openai",
        connection_args = {
            "uri": os.getenv('ZILLIZ_CLOUD_URI'),
            "token": os.getenv( 'ZILLIZ_CLOUD_API_KEY')
        }
    )

    return store