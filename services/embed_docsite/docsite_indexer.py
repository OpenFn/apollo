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

logger = create_logger("DocsiteIndexer")

class DocsiteIndexer:
    """
    Initialize vectorstore and insert new documents. Create a new index if needed.

    :param collection_name: Vectorstore collection name (namespace) to store documents
    :param index_name: Vectorstore index name (default: docsite)
    :param embeddings: LangChain embedding type (default: OpenAIEmbeddings())
    :param dimension: Embedding dimension (default: 1536 for OpenAI Embeddings)
    """
    def __init__(self, collection_name, index_name="docsite", embeddings=OpenAIEmbeddings(), dimension=1536):
        self.collection_name = collection_name
        self.index_name = index_name
        self.embeddings = embeddings
        self.dimension = dimension
        self.pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

        if not self.index_exists():
            self.create_index()

        self.index = self.pc.Index(self.index_name)
        self.vectorstore = PineconeVectorStore(index_name=index_name, namespace=collection_name, embedding=embeddings)

    def insert_documents(self, inputs, metadata_dict):
        """
        Create the index if it does not exist and insert the input documents.
        
        :param inputs: Dictionary containing name, docs_type, and doc_chunk 
        :param metadata_dict: Metadata dict with document titles as keys (from DocsiteProcessor)
        :return: Initialized indices
        """

        # Get vector count before insertion for verification
        try:
            stats = self.index.describe_index_stats()
            vectors_before = stats.namespaces.get(self.collection_name, {}).get("vector_count", 0)
            logger.info(f"Current vector count in namespace '{self.collection_name}': {vectors_before}")
        except Exception as e:
            logger.warning(f"Could not get vector count before insertion: {str(e)}")
            vectors_before = 0

        df = self.preprocess_metadata(inputs=inputs, metadata_dict=metadata_dict)
        logger.info(f"Input metadata preprocessed")
        loader = DataFrameLoader(df, page_content_column="text")
        docs = loader.load()
        logger.info(f"Inputs processed into LangChain docs")
        logger.info(f"Uploading {len(docs)} documents to index...")

        idx = self.vectorstore.add_documents(
            documents=docs
        )
        sleep_time = 10
        max_wait_time = 150
        elapsed_time = 0
        logger.info(f"Waiting up to {max_wait_time}s to verify upload count")

        while elapsed_time < max_wait_time:
            time.sleep(sleep_time)
            elapsed_time += sleep_time
        
            # Verify the upload by checking the vector count
            try:
                stats = self.index.describe_index_stats()
                vectors_after = stats.namespaces.get(self.collection_name, {}).get("vector_count", 0)
                logger.info(f"Vector count after {elapsed_time}s: {vectors_after}")
                
                if vectors_after >= vectors_before + len(docs):
                    logger.info(f"Successfully added {vectors_after - vectors_before} vectors to namespace '{self.collection_name}'")
                    break
                else:
                    logger.warning(f"No new vectors were added to namespace '{self.collection_name}' after {sleep_time}s")
            except Exception as e:
                logger.warning(f"Could not verify vector insertion: {str(e)}")
        
        if vectors_after <= vectors_before:
            logger.warning(f"Could not verify full dataset upload to namespace '{self.collection_name}' after {max_wait_time}s")
    
        return idx

    def delete_collection(self):
        """
        Deletes the entire collection (namespace) and all its contents.
        This operation cannot be undone and removes both the collection structure
        and all vectors/documents within it.
        """
        self.index.delete(delete_all=True, namespace=self.collection_name)

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

    def index_exists(self):
        """Check if the index exists in Pinecone."""
        existing_indexes = [index_info["name"] for index_info in self.pc.list_indexes()]

        return self.index_name in existing_indexes
            
    def preprocess_metadata(self, inputs, page_content_column="text", add_chunk_as_metadata=False, metadata_cols=None, metadata_dict=None):
        """
        Create a DataFrame for indexing from input documents and metadata.
        
        :param inputs: Dictionary containing name, docs_type, and doc_chunk
        :param page_content_column: Name of the field which will be embedded (default: text)
        :param add_chunk_as_metadata: Copy the text to embed as a separate metadata field (default: False)
        :param metadata_cols: Optional list of metadata columns to include (default: None)
        :param metadata_dict: Dictionary mapping names to metadata dictionaries (default: None)
        :return: pandas.DataFrame with text and metadata columns
        """
        
        # Create DataFrame from the inputs (doc_chunk, name, docs_type)
        df = pd.DataFrame(inputs)
        
        # Rename some columns for metadata upload
        df = df.rename(columns={"doc_chunk": page_content_column, "name": "doc_title"})

        df["doc_title"] = df["doc_title"].str.replace(".md$", "", regex=True)

        # Optionally add chunk to metadata for keyword searching
        if add_chunk_as_metadata:
            df["embedding_text"] = df[page_content_column]
        
        # Add further metadata columns if specified
        if metadata_cols:
            for col in metadata_cols:
                df[col] = metadata_dict.get(inputs["name"], {}).get(col)
                
        return df






    