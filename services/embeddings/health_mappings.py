import os
from dotenv import load_dotenv
import json
from embeddings.embeddings import VectorStore
from embeddings.utils import load_json
from datasets import load_dataset
from langchain_community.document_loaders import DataFrameLoader
import pandas as pd

def connect_loinc():
    """Initialise the vector store for LOINC embeddings."""

    load_dotenv()

    store = VectorStore(
        collection_name="loinc_mappings",
        index_name="apollo-mappings",
        vectorstore_type="pinecone",
        embedding_type="openai"
    )

    return store

def connect_snomed():
    """Initialise the vector store for SNOMED embeddings."""

    load_dotenv()

    store = VectorStore(
        collection_name="snomed_mappings",
        index_name="apollo-mappings",
        vectorstore_type="pinecone",
        embedding_type="openai"
    )

    return store

def preprocess_loinc(df, keep_cols, embed_cols):
    """Preprocess a Huggingface LOINC dataframe and populate a Pinecone vector store instance with the data."""

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

def preprocess_snomed(df, keep_cols, embed_cols, project_value_sets):
    """Preprocess a Huggingface SNOMED dataframe and populate a Pinecone vector store instance with the data."""

    # Select dataset columns to include
    df = df[keep_cols]
    
    # Select the SNOMED Value Sets to include
    df = df[df["Value Set Name"].isin(project_value_sets)]

    # Combine selected columns in a JSON string. This new combined field will be embedded and used for searching.
    df["text"] = df[embed_cols].apply(
        lambda row: json.dumps({col: row[col] for col in embed_cols}),
        axis=1
    )

    return df

def upload_loinc_data(store, 
                       keep_cols=["LONG_COMMON_NAME", "METHOD_TYP", "CLASS", "SYSTEM"],
                       embed_cols=["LONG_COMMON_NAME", "METHOD_TYP", "CLASS", "SYSTEM"],):
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

def upload_snomed_data(store, 
                       keep_cols=["Value Set Name", "Code", "Description", "Purpose: Clinical Focus"],
                       embed_cols=["Value Set Name", "Description", "Purpose: Clinical Focus"],
                       project_value_sets=["Body Site Value Set", "Procedure"]):
    """Preprocess a Huggingface SNOMED dataset and populate a Pinecone vector store instance with the data."""
    
    # Get the data as a dataframe
    df = load_dataset("awacke1/SNOMED-CT-Code-Value-Semantic-Set.csv")
    df = pd.DataFrame(df['train'])

    # Preprocess and filter the dataframe
    df = preprocess_snomed(df, keep_cols, embed_cols, project_value_sets)

    # Create a new collection in the vector store and add the data
    loader = DataFrameLoader(df, page_content_column="text")
    docs = loader.load()
    store.add_docs(docs)

    return store

