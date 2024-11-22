import os
from dotenv import load_dotenv
from generate_embeddings import VectorStore
from utils import load_json

load_dotenv()

# This function is used by other services for easy
# access to the embeddings
def search():
    return store.search("manual data entry", search_kwargs={"k": 1})

# This function initialises the store
# so that it can be used later
# SOMEONE will need to run this setup step, I'm not really sure who yet
def setup():

    # Get chat data to insert in database as LangChain documents
    docs = load_json("demo_data/data.json", jq_schema='.messages[].content')

    # Initialise the vector store instance
    store = VectorStore(
        collection_name="demo_project",
        vectorstore_type="zilliz",
        embedding_type="openai",
        connection_args = {
            "uri": os.getenv('ZILLIZ_CLOUD_URI'),
            "token": os.getenv('ZILLIZ_CLOUD_API_KEY')
        }
    )

    # Create a new collection in the vector store for the chat data
    store.create_collection(docs)

