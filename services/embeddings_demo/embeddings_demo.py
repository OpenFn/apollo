import os
from dotenv import load_dotenv
from embeddings import example

load_dotenv(override=True)

def run_demo(input_query):

    # Initialise the vector store instance
    store = example.connect()

    # Add data to the vector store instance
    example.load_default_data(store)

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