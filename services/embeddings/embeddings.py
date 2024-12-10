import os
import argparse
from dataclasses import dataclass, asdict
import warnings
from dotenv import load_dotenv
from langchain_community.vectorstores import Zilliz
from langchain_pinecone import Pinecone
from langchain_openai import OpenAIEmbeddings

@dataclass
class SearchResult:
    """
    Dataclass for VectorStore search results.
    """
    text: str
    metadata: dict
    score: float = None
    
    def to_json(self):
        return {k: v for k, v in asdict(self).items()}

class VectorStore:
    """
    Manages vector embeddings and similarity searches for document collections.
    
    Args:
        collection_name (str): Name of the vector collection
        vectorstore_type (str): Type of vector store (e.g., 'zilliz')
        embedding_type (str): Type of embedding model (e.g., 'openai')
        connection_args (dict): Connection arguments for the vector store
    """
    def __init__(self, collection_name='LangChainCollection', vectorstore_type='zilliz', 
                 embedding_type='openai', connection_args=None, index_name=None):
        self.collection_name = collection_name
        self.vectorstore_type = vectorstore_type.lower()
        self.embedding_type = embedding_type.lower()
        self.connection_args = connection_args
        self.index_name = index_name
        
        self.embedding_classes = {
            'openai': OpenAIEmbeddings
        }

        self.embedding_function = self._get_embedding_class()
        
        self.vectorstore_classes = {
            'zilliz': Zilliz,
            'pinecone': Pinecone
        }

        self.store_kwargs_mappings = {
            'zilliz': {'collection_name': self.collection_name,'connection_args':self.connection_args, 'drop_old': True, 'auto_id':True},
            'pinecone': {'namespace': self.collection_name, 'index_name': self.index_name},
        }

        self.search_init_kwargs_mappings = {
            'zilliz': {'embedding_function': self.embedding_function, 'collection_name': self.collection_name, 'connection_args':self.connection_args},
            'pinecone': {'embedding': self.embedding_function, 'namespace': self.collection_name, 'index_name': self.index_name},
        }
        

        self.VectorStoreClass = self._get_vectorstore_class()
        self.store_kwargs = self._get_vectorstore_kwargs()
        self.search_init_kwargs = self._get_search_init_kwargs()


    
    def _get_embedding_class(self):
        """Get embedding class based on the specified type."""
        try:
            EmbeddingClass = self.embedding_classes[self.embedding_type]
            return EmbeddingClass()
        except KeyError:
            raise ValueError(f"Unsupported embedding type: {self.embedding_type}")
    
    def _get_vectorstore_class(self):
        """Get vectorstore class based on the specified type."""
        try:
            return self.vectorstore_classes[self.vectorstore_type]
        except KeyError:
            raise ValueError(f"Unsupported vectorstore type: {self.vectorstore_type}")
    
    def _get_vectorstore_kwargs(self):
        """Get vectorstore settings based on the specified type."""
        try:
            return self.store_kwargs_mappings[self.vectorstore_type]
        except KeyError:
            raise ValueError(f"Unsupported vectorstore type: {self.vectorstore_type}")
        
    def _get_search_init_kwargs(self):
        """Get vectorstore settings based on the specified type."""
        try:
            return self.search_init_kwargs_mappings[self.vectorstore_type]
        except KeyError:
            raise ValueError(f"Unsupported vectorstore type: {self.vectorstore_type}")  
    
    
    def add_docs(self, docs, **kwargs):
        """
        Create a new collection from documents and initialise it with the specified settings.
        
        Args:
            docs: List of documents to add to the vectorstore
            drop_old: Whether to drop existing collection if it exists (default: True)
            **kwargs: Additional arguments passed to vectorstore initialisation
            
        Returns:
            Initialised vectorstore containing the input documents
        """

        return self.VectorStoreClass.from_documents(
            documents=docs,
            embedding=self.embedding_function,
            **self.store_kwargs,
        )
    
    def search(self, input_text, search_type="similarity", search_kwargs={"k": 2}):
        """
        Retrieve similar texts from a vectorstore based on input text.
        
        Args:
            input_text: Text string to use for similarity search
            search_type: Type of search to perform (default is 'similarity'; others e.g 'similarity_score_threshold')
            search_kwargs: Additional arguments for the search (default retrieves top 2 results)
        
        Returns:
            List of page contents of the most similar documents
        """
        store = self.VectorStoreClass(
            **self.search_init_kwargs,
        )
        retriever = store.as_retriever(search_type=search_type, search_kwargs=search_kwargs)
        retrieved_docs = retriever.invoke(input_text)
        retrieved_texts = [t.page_content for t in retrieved_docs]

        if not retrieved_texts:
            warnings.warn(
                f"\nNo results found. This could mean:\n"
                f"1. Collection '{self.collection_name}' doesn't exist (run add_docs first)\n"
                f"2. No similar documents found (check the input or the search criteria)\n"
                f"3. Connection issues"
        )
            return None
        else:
            results = []
            metadata_dicts = [t.metadata for t in retrieved_docs]

            for text, metadata in zip(retrieved_texts, metadata_dicts):
                results.append(SearchResult(text, metadata))
            
            return results