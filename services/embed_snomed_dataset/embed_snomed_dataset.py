import os
import json
from dotenv import load_dotenv
from embeddings import snomed_store
import pandas as pd
from datasets import load_dataset
from langchain_community.document_loaders import DataFrameLoader

load_dotenv(override=True)

def preprocess_snomed(df, keep_cols, embed_cols, project_value_sets):
    """Preprocess a Huggingface SNOMED dataframe."""

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
    print("Dataset preprocessed")

    # Create a new collection in the vector store and add the data
    loader = DataFrameLoader(df, page_content_column="text")
    docs = loader.load()
    store.add_docs(docs)

    return store

def embed_snomed_dataset():
    # Initialise the vector store instance
    store = snomed_store.connect_snomed()

    # Embed and uplaod data to the vector store instance
    upload_snomed_data(store)

    return store

def main(data):
    print("Starting...")
    store = embed_snomed_dataset()
    print("Embedded and uploaded SNOMED dataset to a Pinecone vectorstore")

    input_query = data.get("query", "")
    print(f"Test: Searching for similar texts to {input_query}")
    results = store.search(input_query, search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.88})
    print(results)

    return {
            "input_text": input_query,
            "similar_text": results[0]
        }

if __name__ == "__main__":
    main()