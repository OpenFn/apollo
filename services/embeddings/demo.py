"""
This is an example of how another service (like job_chat or adaptor_gen)
might use an embedding store
If we made it a top-level service, like `embedding_demo`, it would be
callable from the apollo endpoints or the CLI
"""

# I don't actually know what we import form the store module
# a store instance? A constructor? A search and load function?
# I think a search function would be nice
from .example import search

def main():
    input_query="manual data entry"

    results = search(input_query)

    print(f"Input text: {input_query}\nMost similar text in the database: {results[0]}")

if __name__ == "__main__":
    main()