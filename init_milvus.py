import os
import time
import glob
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymilvus import FieldSchema, CollectionSchema, DataType, utility, Collection, connections, model

load_dotenv()


def read_md_files(directory):
    md_files = glob.glob(f"{directory}/**/*.md", recursive=True)
    docs = []
    for file in md_files:
        with open(file, "r", encoding="utf-8") as f:
            docs.append(f.read())
    return docs

def split_md_by_sections(content):
    # I don't know if this is efficient or not, it leads to uneven chunking of sections and hence affects the search results\
    # After some testing the search results seem to be better for recursive splitting
    # headers_to_split_on = [
    #     ("##", "Header 2"),
    #     ("###", "Header 3"),
    # ]

    # markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
    # md_header_splits = markdown_splitter.split_text(content)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=128, length_function=len, is_separator_regex=False,)
    
    splits = text_splitter.split_text(content)
    return splits

if __name__ == "__main__":
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_ef = model.dense.OpenAIEmbeddingFunction(
        model_name="text-embedding-ada-002", 
        api_key=openai_key
    )

    # Read markdown files from the repo
    docs_path = "/app/repo/docs"
    corpus = []
    md_files_content = read_md_files(docs_path)
    for content in md_files_content:
        sections = split_md_by_sections(content)
        corpus.extend(sections)

    # Embed the corpus
    embeddings = openai_ef.encode_documents(corpus)

    # Connect to Milvus
    milvus_uri = os.getenv('MILVUS_URI')
    token = os.getenv('MILVUS_TOKEN')
    print(f"Connecting to DB: {milvus_uri}")
    connections.connect("default", uri=milvus_uri, token=token, db_name="apollo_db")

    # Check if the collection exists
    collection_name = "apollo_sample"
    check_collection = utility.has_collection(collection_name)
    if check_collection:
        drop_result = utility.drop_collection(collection_name)

    # Define field schemas
    id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True, description="primary id")
    embedding_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536, description="vector")
    text_field = FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=1100, description="text data")

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