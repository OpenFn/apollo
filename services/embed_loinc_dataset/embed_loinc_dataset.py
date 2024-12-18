import os
import json
from dotenv import load_dotenv
from embeddings import loinc_store
import pandas as pd
from datasets import load_dataset
from langchain_community.document_loaders import DataFrameLoader

load_dotenv(override=True)

def preprocess_loinc(df, keep_cols, embed_cols):
    """Preprocess a Huggingface LOINC dataframe."""

    # Select dataset columns to include
    df = df[keep_cols]

    # Replace NULL values with empty string
    df = df.fillna('')
    
    # Combine selected columns in a JSON string. This new combined field will be embedded and used for searching.
    df["text"] = df[embed_cols].apply(
        lambda row: json.dumps({col: row[col] for col in embed_cols}),
        axis=1
    )

    return df

def upload_loinc_data(store, 
                       keep_cols=["LONG_COMMON_NAME", "METHOD_TYP", "CLASS", "SYSTEM"],
                       embed_cols=["LONG_COMMON_NAME", "METHOD_TYP", "CLASS", "SYSTEM"]):
    """Preprocess a Huggingface LOINC dataset and populate a Pinecone vector store instance with the data."""
    
    # Get the data as a dataframe
    df = load_dataset("awacke1/LOINC-Clinical-Terminology")
    df = pd.DataFrame(df['train'])

    # Preprocess and filter the dataframe
    df = preprocess_loinc(df, keep_cols, embed_cols)

    # Create a new collection in the vector store and add the data
    loader = DataFrameLoader(df, page_content_column="text")
    docs = loader.load()
    store.add_docs(docs)

    return store

def embed_loinc_dataset():
    # Initialise the vector store instance
    store = loinc_store.connect_loinc()

    # Embed and uplaod data to the vector store instance
    upload_loinc_data(store)

    return store

def main(data):
    store = embed_loinc_dataset()
    print("Embedded and uploaded LOINC dataset to a Pinecone vectorstore")

    input_query = data.get("query", "")
    print(f"Test: Searching for similar texts to {input_query}")
    print(store.search(input_query, search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.88}))

if __name__ == "__main__":
    main()