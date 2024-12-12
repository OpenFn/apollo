import os
from dotenv import load_dotenv
from embeddings import health_mappings

load_dotenv(override=True)

def embed_loinc_dataset(input_query):

    # Initialise the vector store instance
    store = health_mappings.connect_loinc()

    # Embed and uplaod data to the vector store instance
    health_mappings.upload_loinc_data(store)

def main(data):
    embed_loinc_dataset()
    print("Embedded and uploaded LOINC dataset to a Pinecone vectorstore")

if __name__ == "__main__":
    main()