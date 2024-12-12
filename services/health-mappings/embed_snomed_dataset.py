import os
from dotenv import load_dotenv
from embeddings import health_mappings

load_dotenv(override=True)

def embed_snomed_dataset(input_query):

    # Initialise the vector store instance
    store = health_mappings.connect_snomed()

    # Embed and uplaod data to the vector store instance
    health_mappings.upload_snomed_data(store)

def main(data):
    embed_snomed_dataset()
    print("Embedded and uploaded SNOMED dataset to a Pinecone vectorstore")

if __name__ == "__main__":
    main()