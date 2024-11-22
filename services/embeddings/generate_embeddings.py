import os
import argparse
import warnings
from dotenv import load_dotenv
from langchain_community.vectorstores import Zilliz
from langchain_openai import OpenAIEmbeddings

class VectorStore:
    """
    Manages vector embeddings and similarity searches for document collections.
    
    Args:
        collection_name (str): Name of the vector collection
        vectorstore_type (str): Type of vector store (e.g., 'zilliz')
        embedding_type (str): Type of embedding model (e.g., 'openai')
        connection_args (dict): Connection arguments for the vector store
        auto_id (bool): Whether to automatically generate IDs
    """
    def __init__(self, collection_name='LangChainCollection', vectorstore_type='zilliz', 
                 embedding_type='openai', connection_args=None, auto_id=True):
        self.collection_name = collection_name
        self.vectorstore_type = vectorstore_type.lower()
        self.embedding_type = embedding_type.lower()
        self.connection_args = connection_args
        self.auto_id = auto_id
        
        self.embedding_classes = {
            'openai': OpenAIEmbeddings
        }
        
        self.vectorstore_classes = {
            'zilliz': Zilliz
        }
        
        self.embedding_function = self._get_embedding_class()
        self.VectorStoreClass = self._get_vectorstore_class()
    
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
    
    def create_collection(self, docs, drop_old=True, **kwargs):
        """
        Create a new vectorstore from documents and initialise it with the specified settings.
        
        Args:
            docs: List of documents to add to the vectorstore
            drop_old: Whether to drop existing collection if it exists (default: True)
            **kwargs: Additional arguments passed to vectorstore initialisation
            
        Returns:
            Initialised vectorstore containing the input documents
        """
        store_kwargs = {
            'collection_name': self.collection_name,
            **kwargs
        }
        if self.connection_args:
            store_kwargs['connection_args'] = self.connection_args
            
        return self.VectorStoreClass.from_documents(
            documents=docs,
            embedding=self.embedding_function,
            auto_id=self.auto_id,
            drop_old=drop_old,
            **store_kwargs
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
            embedding_function=self.embedding_function,
            auto_id=self.auto_id,
            collection_name=self.collection_name,
            connection_args=self.connection_args
        )
        retriever = store.as_retriever(search_type=search_type, search_kwargs=search_kwargs)
        retrieved_docs = retriever.invoke(input_text)
        results = [t.page_content for t in retrieved_docs]

        if not results:
            warnings.warn(
                f"\nNo results found. This could mean:\n"
                f"1. Collection '{self.collection_name}' doesn't exist (run create_collection first)\n"
                f"2. No similar documents found (check the input or the search criteria)\n"
                f"3. Connection issues"
        )
        return results


def main():
    parser = argparse.ArgumentParser(description="Search similar texts in vector collection")
    parser.add_argument("--input_text", type=str, required=True)
    parser.add_argument("--collection_name", type=str, required=True)
    parser.add_argument("--vectorstore_type", type=str, default="zilliz")
    parser.add_argument("--embedding_model", type=str, default="openai")
    args = parser.parse_args()

    load_dotenv()
    
    connection_args = {
        "uri": os.getenv('ZILLIZ_CLOUD_URI'),
        "token": os.getenv('ZILLIZ_CLOUD_API_KEY')
    }

    store = VectorStore(
        collection_name=args.collection_name,
        vectorstore_type=args.vectorstore_type,
        embedding_type=args.embedding_model,
        connection_args=connection_args
    )
    
    results = store.search(args.input_text)
    print(results)

if __name__ == "__main__":
    main()