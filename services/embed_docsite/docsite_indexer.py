import os
import time
from datetime import datetime
import json
import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_community.document_loaders import DataFrameLoader
from util import create_logger, ApolloError
from embed_docsite.docsite_processor import DocsiteProcessor

logger = create_logger("DocsiteIndexer")

class DocsiteIndexer:
    """
    Initialise vectorstore and add new index or documents.
    """
    def __init__(self, index_name, collection_name="docsite", dimension = 1536):
        self.collection_name = collection_name
        self.index_name = index_name
        self.dimension = dimension
        self.pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
        self.vectorstore = PineconeVectorStore

    def index_exists(self):
        """Check if the index exists in Pinecone."""
        existing_indexes = [index_info["name"] for index_info in self.pc.list_indexes()]

        return self.index_name in existing_indexes
    
    def create_index(self):
        """Creates a new Pinecone index if it does not exist."""
        
        if not self.index_exists():
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        while not self.pc.describe_index(self.index_name).status["ready"]:
            time.sleep(1)
            
    def delete_index(self):
        """Deletes the entire index and all its contents.
        This operation cannot be undone and removes both the index structure
        and all vectors/documents within it."""
        self.pc.delete_index(self.index_name)

    def preprocess_metadata(self, inputs, page_content_column="text", add_chunk_as_metadata=True, metadata_cols=None, metadata_dict=None):
        """
        Create a DataFrame for indexing from input documents and metadata.
        
        :param inputs: Dictionary containing name, docs_type, and doc_chunk
        :param metadata_dict: Dictionary mapping names to metadata dictionaries
        :param metadata_cols: Optional list of metadata columns to include
        :return: pandas.DataFrame with text and metadata columns
        """
        
        # Create DataFrame from the inputs (doc_chunk, name, docs_type)
        df = pd.DataFrame(inputs)
        
        # Rename some columns for metadata upload
        df = df.rename(columns={"doc_chunk": page_content_column, "name": "doc_title"})

        # Optionally add chunk to metadata for keyword searching
        if add_chunk_as_metadata:
            df["embedding_text"] = df[page_content_column]
        
        # Add further metadata columns if specified
        if metadata_cols:
            for col in metadata_cols:
                df[col] = metadata_dict.get(inputs["name"], {}).get(col)
                
        return df

    def insert_documents(self, inputs, metadata_dict, embeddings=OpenAIEmbeddings):
        """
        Create the index if it does not exist and inster the inputs.
        
        :param embeddings: inputs
        :param metadata_dict: Metadata dict with document titles as keys (from DocsiteProcessor)
        :param embeddings: Embedding type
        :return: vectorstore initialized with the inputs
        """

        df = self.preprocess_metadata(inputs, metadata_dict)
        loader = DataFrameLoader(df, page_content_column="text")
        docs = loader.load()

        if not self.index_exists():
            self.create_index()

        return self.vectorstore.from_documents(
            documents=docs,
            embedding=embeddings,
            namespace=self.collection_name,
            index_name=self.index_name
        )