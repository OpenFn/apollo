import os
import time
import glob
import argparse
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from pymilvus import FieldSchema, CollectionSchema, DataType, utility, Collection, connections, model

load_dotenv()

def read_md_files(directory):
    md_files = glob.glob(f"{directory}/**/*.md", recursive=True)
    docs = []
    for file in md_files:
        with open(file, "r", encoding="utf-8") as f:
            docs.append((file, f.read()))  # Returning a tuple with file name and content
    return docs

def split_md_by_sections(file_name, content):
    headers_to_split_on = [
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
    md_header_splits = markdown_splitter.split_text(content)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=256, length_function=len, is_separator_regex=False)
    splits = text_splitter.split_documents(md_header_splits)

    # Write the sections to disk
    output_dir = "./tmp/split_sections"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f"{os.path.basename(file_name)}_sections.md"), "w", encoding="utf-8") as out_file:
        for section in splits:
            out_file.write(f"## Section Start: " + "\n------\n")
            out_file.write(section.page_content + "\n------\n")

    return splits

if __name__ == "__main__":
    # Parse the command line arguments - repo_path and collection_name
    parser = argparse.ArgumentParser(description="Initialize Milvus with markdown files")  
    parser.add_argument("repo_path", type=str, help="Path to the repository containing markdown files")
    parser.add_argument("collection_name", type=str, help="Name of the Milvus collection")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY")
    openai_ef = model.dense.OpenAIEmbeddingFunction(
        model_name="text-embedding-ada-002", 
        api_key=openai_key
    )

   # Read markdown files from the repo
    docs_path = args.repo_path
    corpus = []
    md_files_content = read_md_files(docs_path)
    
    file_embeddings_count = {}
    
    for file_name, content in md_files_content:
        sections = split_md_by_sections(file_name, content)
        corpus.extend(section.page_content for section in sections)
        file_embeddings_count[file_name] = len(sections)  # Store the count of embeddings per file
  
    # Log the number of embeddings per file
    for file_name, count in file_embeddings_count.items():
        print(f"File: {file_name} - Generated {count} embeddings")
    
    print(f"Read {len(corpus)} documents from {docs_path}")

    # Embed the corpus
    embeddings = openai_ef.encode_documents(corpus)

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

    # Define field schemas
    id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True, description="primary id")
    embedding_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536, description="vector")
    text_field = FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=950, description="text data")

    # Define collection schema
    schema = CollectionSchema(fields=[id_field, embedding_field, text_field], description="Corpus collection schema")

    # Create collection
    print(f"Creating example collection: {collection_name}")
    collection = Collection(name=collection_name, schema=schema)
    print("Collection created!")

    # Insert data
    collection.insert([
        embeddings,  # embeddings
        corpus      # original text
    ])

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
    default_index = {"index_type": "SCANN", "metric_type": "COSINE", "params": {"nlist": 16384}}
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
