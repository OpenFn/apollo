import os
import time
import argparse
from openai import OpenAI
from dotenv import load_dotenv
from pymilvus import FieldSchema, CollectionSchema, DataType, utility, Collection, connections
from utils import split_docs, read_md_files, read_paths_config

load_dotenv()

if __name__ == "__main__":
    # Parse the command line arguments - repo_path and collection_name
    parser = argparse.ArgumentParser(description="Initialize Milvus with markdown files")  
    parser.add_argument("repo_path", type=str, help="Path to the repository containing markdown files")
    parser.add_argument("collection_name", type=str, help="Name of the Milvus collection")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=openai_key)

    # Read paths from the configuration file
    docs_to_embed = read_paths_config("./path.config", args.repo_path)
    corpus = []
    md_files_content = read_md_files(docs_to_embed)

    file_embeddings_count = {}
    for file_name, content in md_files_content:
        sections = split_docs(file_name, content)
        corpus.extend(section.page_content for section in sections)
        file_embeddings_count[file_name] = len(sections)  # Store the count of embeddings per file

    # Log the number of embeddings per file
    for file_name, count in file_embeddings_count.items():
        print(f"File: {file_name} - Generated {count} embeddings")
    
    print(f"Read {len(corpus)} documents.")

    # Embed the corpus
    print("Embedding documents...")
    vectors = [
        vec.embedding
        for vec in client.embeddings.create(input=corpus, model="text-embedding-3-small").data
    ]

    data = [
        {
            "embedding": vectors[i], 
            "text": corpus[i]
        }
        for i in range(len(corpus))
    ]

    # Connect to Milvus
    zilliz_uri = os.getenv('ZILLIZ_URI')
    token = os.getenv('ZILLIZ_TOKEN')
    print(f"Connecting to DB: {zilliz_uri}")
    connections.connect("default", uri=zilliz_uri, token=token, db_name="openfn_docs")

    # Check if the collection exists
    collection_name = args.collection_name
    check_collection = utility.has_collection(collection_name)
    if check_collection:
        drop_result = utility.drop_collection(collection_name)

    # Define field schemas, using the max overall split length for the text field
    id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True, description="primary id")
    embedding_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536, description="vector")
    text_field = FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=1100, description="text data")

    # Define collection schema
    schema = CollectionSchema(fields=[id_field, embedding_field, text_field], description="Corpus collection schema")

    # Create collection
    print(f"Creating collection: {collection_name}")
    collection = Collection(name=collection_name, schema=schema)
    print("Collection created!")

    # Insert data
    collection.insert(data)

    # Flush
    print("Flushing...")
    start_flush = time.time()
    collection.flush()
    end_flush = time.time()
    print(f"Succeed in {round(end_flush - start_flush, 4)} seconds!")

    # Building index
    if utility.has_collection(collection_name):
        collection = Collection(name=collection_name)
    t0 = time.time()
    default_index =  {
        'index_type': 'IVF_FLAT',
        'metric_type': 'L2',
        'params': {'nlist': 1024}
    }
    status = collection.create_index(field_name="embedding", index_params=default_index)
    t1 = time.time()
    if not status.code:
        print(f"Successfully created index in collection: {collection_name} in {round(t1-t0, 4)} seconds")

    # Load collection
    t0 = time.time()
    print("Loading collection...")
    collection.load()
    t1 = time.time()
    print(f"Loaded collection in {round(t1-t0, 4)} seconds!")

    print("Milvus database configured successfully!")
