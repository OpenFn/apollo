import os
import argparse
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader, JSONLoader
from langchain_community.vectorstores import Zilliz
from langchain_openai import OpenAIEmbeddings


def parse_arguments():
    """
    Parses command line arguments.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Fetch similar texts from an existing vector collection")
    parser.add_argument("--input_text", type=str, help="The string against which vectors will be compared")
    parser.add_argument("--collection_name", type=str, help="Name of the vector collection")
    parser.add_argument("--vectorstore_type", type=str, help="Name of the vector store e.g. Zilliz")
    parser.add_argument("--embedding_model", type=str, help="The embedding model type, e.g. OpenAI")

    return parser.parse_args()

def get_json(f, jq_schema):
    """Wrapper around LangChain JSONLoader, using the same arguments."""
    loader = JSONLoader(
        file_path=f,
        jq_schema=jq_schema,
        text_content=False
        )
    documents = loader.load()

    return documents


def _get_embedding_class(embedding_type="openai"):
    """
    Get embedding class based on the specified type.
    
    Args:
        embedding_type: Type of embedding to use (default is 'openai')
    
    Returns:
        Instantiated embedding class
    """
    embedding_classes = {
        'openai': OpenAIEmbeddings,
        # 'huggingface': HuggingFaceEmbeddings,
        # Add other embedding types here
    }
    
    try:
        EmbeddingClass = embedding_classes[embedding_type.lower()]
        return EmbeddingClass()
    except KeyError:
        raise ValueError(f"Unsupported embedding type: {embedding_type}")

def _get_vectorstore_config(vectorstore_type='zilliz', connection_args=None, **kwargs):
    """
    Internal helper to get vectorstore class and configuration.
    
    Args:
        vectorstore_type: Name of vectorstore class (lowercase)
        connection_args: Dictionary of connection arguments for specific vectorstores (e.g. Zilliz)
        **kwargs: Additional parameters for vectorstore initialisation
    Returns:
        A vectorstore LangChain class and the relevant arguments to use for it.
    """
    vectorstore_classes = {
        'zilliz': Zilliz
        # Test other vectorstore classes from LangChain and add here
    }
    
    try:
        VectorStoreClass = vectorstore_classes[vectorstore_type.lower()]
        
        # Build kwargs dictionary
        init_kwargs = {
            # 'embedding_function': embedding,
            **kwargs
        }
        
        # Add connection args if provided
        if connection_args:
            init_kwargs['connection_args'] = connection_args
            
        return VectorStoreClass, init_kwargs
        
    except KeyError:
        raise ValueError(f"Unsupported vectorstore type: {vectorstore_type}")

def create_store(docs, collection_name='LangChainCollection', vectorstore_type='zilliz', embedding="openai",
                        connection_args=None, auto_id=True, drop_old=True, **kwargs):
    """
   Create a new vectorstore from documents and initialise it with the specified settings.
   
   Args:
       docs: List of documents to add to the vectorstore
       collection_name: Name of the collection to create (default: 'LangChainCollection')
       vectorstore_type: Type of vectorstore to create (e.g. 'zilliz')
       embedding: Type of embedding model to use (e.g. 'openai')
       connection_args: Connection arguments for the vectorstore if needed(e.g. URI, API key)
       auto_id: Whether to automatically generate IDs (default: True)
       drop_old: Whether to drop existing collection if it exists (default: True)
       **kwargs: Additional arguments passed to vectorstore initialisation
       
   Returns:
       Initialised vectorstore containing the input documents
    """
    VectorStoreClass, init_kwargs = _get_vectorstore_config(
        vectorstore_type=vectorstore_type,
        # embedding=embedding,
        connection_args=connection_args,
        collection_name=collection_name,
        **kwargs
    )
    
    return VectorStoreClass.from_documents(documents=docs, embedding=_get_embedding_class(embedding), auto_id=auto_id, drop_old=drop_old, **init_kwargs)

def get_store(collection_name='LangChainCollection', vectorstore_type='zilliz', 
                           embedding="openai", connection_args=None, auto_id=True, **kwargs):
    """
   Get an existing vectorstore collection and configure it with specified settings.
   
   Args:
       collection_name: Name of the collection to retrieve (default: 'LangChainCollection')
       vectorstore_type: Type of vectorstore to connect to (e.g. 'zilliz')
       embedding: Type of embedding model to use (e.g. 'openai') 
       connection_args: Connection arguments for the vectorstore (e.g. URI, API key)
       auto_id: Whether to automatically generate IDs (default: True)
       **kwargs: Additional arguments passed to vectorstore initialisation

   Returns:
       Connected vectorstore instance with specified configuration
    """
    VectorStoreClass, init_kwargs = _get_vectorstore_config(
        vectorstore_type=vectorstore_type,
        # embedding=embedding,
        connection_args=connection_args,
        collection_name=collection_name,
        **kwargs
    )
    
    return VectorStoreClass(embedding_function=_get_embedding_class(embedding), auto_id=auto_id, **init_kwargs)


def get_similar_texts(input_text, vectorstore, search_type="similarity", search_kwargs={"k": 2}):
    """
    Retrieve similar texts from a vectorstore based on input text.
    
    Args:
        input_text: Text string to use for similarity search
        vectorstore: Vectorstore to search in
        search_type: Type of search to perform (default is 'similarity'; others e.g 'similarity_score_threshold')
        search_kwargs: Additional arguments for the search (default retrieves top 2 results)
    
    Returns:
        List of page contents of the most similar documents
    """
    retriever = vectorstore.as_retriever(search_type=search_type, search_kwargs=search_kwargs)
    retrieved_docs = retriever.invoke(input_text)

    return [t.page_content for t in retrieved_docs]



def main():
    # Example for fetching similar texts with an input text from an existing vector collection

    args = parse_arguments()

    # Fetch API keys and connection details
    load_dotenv()

    ZILLIZ_CLOUD_URI = os.getenv('ZILLIZ_CLOUD_URI')
    ZILLIZ_CLOUD_API_KEY = os.getenv('ZILLIZ_CLOUD_API_KEY')

    existing_store = get_store(
        collection_name=args.collection_name,
        vectorstore_type=args.vectorstore_type, # currently Zilliz is available
        embedding=args.embedding_model, # currently OpenAI is available
        connection_args={
            "uri": ZILLIZ_CLOUD_URI,
            "token": ZILLIZ_CLOUD_API_KEY,
        }
    )

    result = get_similar_texts(args.input_text, existing_store, search_type="similarity", search_kwargs={"k": 2})
    print(result)

if __name__ == "__main__":
    main()
