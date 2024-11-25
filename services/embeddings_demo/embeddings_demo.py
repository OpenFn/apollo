import os
from dotenv import load_dotenv
from embeddings.embeddings import VectorStore
from embeddings.utils import load_json

load_dotenv()


def run_demo(input_query):

    # Get chat data to insert in database as LangChain documents
    docs = load_json("embeddings_demo/demo_data/data.json", jq_schema='.messages[].content')

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

    # Create a new collection in the vector store and add the chat data
    store.add_docs(docs)

    # Search the chat data in the store with an input text
    results = store.search("manual data entry", search_kwargs={"k": 1})
    return results


def main(data):
    input_query = data.get("query", "")

    results = run_demo(input_query)
    print(f"Input text: {input_query}\nMost similar text in the database: {results[0]}")

    return {
            "input_text": input_query,
            "most_similar_text": results[0]
        }

if __name__ == "__main__":
    main()