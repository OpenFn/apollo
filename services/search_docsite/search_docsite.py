import os
from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from util import create_logger, ApolloError

logger = create_logger("DocsiteSearch")

class DocsiteSearch:
    """WIP"""
    def __init__(self, index_name, default_top_k=10):
        self.index_client = index_name
        self.default_top_k = default_top_k
        self.vector_store = PineconeVectorStore(
            index=index_name,
            embedding=OpenAIEmbeddings()
        )
    
    def search(self, query, filters=None, top_k=None, strategy='semantic'):
        top_k = top_k or self.default_top_k
        
        if strategy == 'semantic':
            return self.semantic_search(query, filters, top_k)
        elif strategy == 'keyword':
            return self.keyword_search(query, filters, top_k)
    
    def semantic_search(self, query, filters, top_k):
        return self.vector_store.similarity_search_with_score(
            query=query,
            k=top_k,
            filter=filters
        )
    
    def keyword_search(self, query, filters, top_k):
        pass


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

    # Initialise search engine
    index_name = "20240218"
    docsite_search = DocsiteSearch(index_name = index_name)

if __name__ == "__main__":
    main()