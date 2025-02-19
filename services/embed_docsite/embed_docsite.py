import os
import time
from datetime import datetime
import json
from dotenv import load_dotenv
import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from util import create_logger, ApolloError
from embed_docsite.docsite_processor import DocsiteProcessor

logger = create_logger("DocsiteIndexer")

class DocsiteIndexer:
    """
    WIP
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

    def insert_documents(self, docs, embeddings=OpenAIEmbeddings):
        """
        Create a new collection from documents and initialise it with the specified settings.
        
        Args:
            docs: List of documents to add to the vectorstore
            drop_old: Whether to drop existing collection if it exists (default: True)
            
        Returns:
            Initialised vectorstore containing the input documents
        """

        if not self.index_exists():
            self.create_index()

        return self.vectorstore.from_documents(
            documents=docs,
            embedding=embeddings,
            namespace=self.collection_name,
            index_name=self.index_name
        )

def main(data):
    logger.info("Starting...")

    # Set API keys
    load_dotenv(override=True)
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')

    # Check for missing keys
    missing_keys = []

    if not OPENAI_API_KEY:
        missing_keys.append("OPENAI_API_KEY") 
    if not PINECONE_API_KEY:
        missing_keys.append("PINECONE_API_KEY")

    if missing_keys:
        msg = f"Missing API keys: {', '.join(missing_keys)}"
        logger.error(msg)
        raise ApolloError(500, f"Missing API keys: {', '.join(missing_keys)}", type="BAD_REQUEST")

    # Get docsite as preprocessed LangChain docs
    docsite_processor = DocsiteProcessor()
    documents = docsite_processor.get_preprocessed_docs()
    
    # Initialize indexer
    current_date = datetime.now().strftime("%Y%m%d")
    index_name = f"docsite-{current_date}"
    docsite_indexer = DocsiteIndexer(index_name=index_name)
    
    # Create index if it does not exist & insert documents
    docsite_indexer.insert_documents(documents)

    logger.info(f"Embedded and uploaded docs to Pinecone index {index_name}")

    # # Test -- use other service
    # input_query = data.get("query", "")
    # logger.info(f"Test: Searching for similar texts to {input_query}")
    # results = store.search(input_query, search_type="similarity_score_threshold", search_kwargs={"score_threshold": 0.88})
    # logger.info(f"Search result: {results}")

    # return {
    #         "input_text": input_query,
    #         "similar_text": results[0]
    #     }

if __name__ == "__main__":
    main()