import os
from dotenv import load_dotenv
from embeddings.embeddings import VectorStore
from embeddings.utils import load_json

def connect():
    """Initialise the vector store instance to be used by the embeddings_demo service."""

    load_dotenv()

    store = VectorStore(
        collection_name="demo_project",
        vectorstore_type="zilliz",
        embedding_type="openai",
        connection_args = {
            "uri": os.getenv('ZILLIZ_URI'),
            "token": os.getenv( 'ZILLIZ_TOKEN')
        }
    )

    return store

def load_default_data(store):
    """Populate the vector store instance to be used by the embeddings_demo service."""

    # Get chat data as LangChain documents
    docs = load_json("embeddings/data/demo/demo_data.json", jq_schema='.messages[].content')

    # Create a new collection in the vector store and add the chat data
    store.add_docs(docs)

    return store