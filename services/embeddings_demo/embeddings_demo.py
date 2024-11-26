import os
from dotenv import load_dotenv
from embeddings.demo.example import get_demo_vectorstore
from embeddings.utils import load_json

load_dotenv()


def run_demo(input_query):

    # Initialise the vector store instance
    store = get_demo_vectorstore()

    # Get chat data to insert in database as LangChain documents
    docs = load_json("embeddings/demo/data/demo_data.json", jq_schema='.messages[].content')

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