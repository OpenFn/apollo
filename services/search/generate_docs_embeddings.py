import os
import time
import argparse
from openai import OpenAI
from dotenv import load_dotenv
from pymilvus import FieldSchema, CollectionSchema, DataType, utility, Collection
from utils import split_docs, read_md_files, read_paths_config, fetch_adaptor_data, process_adaptor_data, connect_to_milvus

load_dotenv()

def parse_arguments():
    """
    Parses command line arguments.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Initialize Milvus with markdown files")
    parser.add_argument("repo_path", type=str, help="Path to the repository containing markdown files")
    parser.add_argument("collection_name", type=str, help="Name of the Milvus collection")
    return parser.parse_args()

def create_collection(collection_name: str, max_chunk_length: int) -> Collection:
    """
    Creates a Milvus collection with the specified schema.

    :param collection_name: Name of the collection to create
    :param max_chunk_length: Maximum length of text field
    :return: Milvus Collection instance
    """
    # Define field schemas
    id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True, description="Primary ID")
    embedding_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536, description="Vector")
    text_field = FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=max_chunk_length, description="Text data")

    # Create collection schema
    schema = CollectionSchema(fields=[id_field, embedding_field, text_field], description="Corpus collection schema")

    # Create the collection
    print(f"Creating collection: {collection_name}")
    collection = Collection(name=collection_name, schema=schema)
    print("Collection created!")

    # Create partitions
    collection.create_partition(partition_name="normal_docs")
    collection.create_partition(partition_name="adaptor_docs")
    print("Partitions 'normal_docs' and 'adaptor_docs' created!")

    return collection

def embed_documents(client: OpenAI, corpus: list, adaptor_corpus: list) -> tuple:
    """
    Embeds documents using the OpenAI API.

    :param client: OpenAI client instance
    :param corpus: List of normal documents to embed
    :param adaptor_corpus: List of adaptor documents to embed
    :return: Tuple containing embedded normal and adaptor documents
    """
    print("Embedding documents...")
    corpus_vectors = client.embeddings.create(input=corpus, model="text-embedding-3-small").data
    adaptor_vectors = client.embeddings.create(input=adaptor_corpus, model="text-embedding-3-small").data
    return corpus_vectors, adaptor_vectors

def insert_data(collection: Collection, vectors: list, texts: list, partition_name: str) -> None:
    """
    Inserts data into a specified partition of the Milvus collection.

    :param collection: Milvus Collection instance
    :param vectors: List of embeddings
    :param texts: List of document texts
    :param partition_name: Name of the partition to insert data into
    """
    data = [{"embedding": vec.embedding, "text": texts[i]} for i, vec in enumerate(vectors)]
    collection.insert(data=data, partition_name=partition_name)
    print(f"Inserted {len(data)} documents into '{partition_name}' partition.")

def main():
    args = parse_arguments()

    # Fetch API keys and connection details
    openai_key = os.getenv("OPENAI_API_KEY")

    # Connect to OpenAI and Milvus
    client = OpenAI(api_key=openai_key)
    connect_to_milvus()

    # Read and process markdown files
    docs_to_embed = read_paths_config("./path.config", args.repo_path)
    md_files_content = read_md_files(docs_to_embed)

    corpus = []
    file_embeddings_count = {}
    
    for file_name, content in md_files_content:
        sections = split_docs(file_name, content)
        corpus.extend(section.page_content for section in sections)
        file_embeddings_count[file_name] = len(sections)

    # Log the number of embeddings per file
    for file_name, count in file_embeddings_count.items():
        print(f"File: {file_name} - Generated {count} embeddings")
    
    print(f"Normal docs split: {len(corpus)}")

    # Fetch and process adaptor data
    adaptor_data = fetch_adaptor_data()
    adaptor_corpus, max_chunk_length = process_adaptor_data(adaptor_data)
    print(f"Adaptor data split: {len(adaptor_corpus)}")

    # Combine normal and adaptor docs
    print(f"Total documents after adding adaptors: {len(corpus) + len(adaptor_corpus)}")

    collection_name = args.collection_name
    check_collection = utility.has_collection(collection_name)
    if check_collection:
        utility.drop_collection(collection_name)

    # Create collection
    collection = create_collection(collection_name=collection_name, max_chunk_length=max_chunk_length)

    # Embed and insert data
    corpus_vectors, adaptor_vectors = embed_documents(client, corpus, adaptor_corpus)

    insert_data(collection, corpus_vectors, corpus, partition_name="normal_docs")
    insert_data(collection, adaptor_vectors, adaptor_corpus, partition_name="adaptor_docs")

    # Flush and create index
    print("Flushing...")
    start_flush = time.time()
    collection.flush()
    end_flush = time.time()
    print(f"Succeeded in {round(end_flush - start_flush, 4)} seconds!")

    print("Creating index...")
    default_index = {'index_type': 'IVF_FLAT', 'metric_type': 'L2', 'params': {'nlist': 1024}}
    collection.create_index(field_name="embedding", index_params=default_index)

    # Load collection
    t0 = time.time()
    print("Loading collection...")
    collection.load()
    t1 = time.time()
    print(f"Loaded collection in {round(t1 - t0, 4)} seconds!")

    print("Milvus database configured successfully!")

if __name__ == "__main__":
    main()
