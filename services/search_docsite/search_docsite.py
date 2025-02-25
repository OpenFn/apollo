import os
from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from util import create_logger, ApolloError

logger = create_logger("DocsiteSearch")

class DocsiteSearch:
    """WIP"""
    def __init__(self, collection_name, index_name="docsite", default_top_k=10, embeddings=OpenAIEmbeddings()):
        self.collection_name = collection_name
        self.index_client = index_name
        self.default_top_k = default_top_k
        self.vectorstore = PineconeVectorStore(index=index_name, namespace=collection_name, embedding=embeddings)
    
    def build_filter(self, **kwargs):
            conditions = []

            # Add exact match conditions
            if kwargs.get('doc_title'):
                conditions.append({"doc_title": {"$eq": kwargs['doc_title']}})
            

            if kwargs.get('docs_type'):
                conditions.append({"docs_type": {"$eq": kwargs['docs_type']}})
            
            # Add text search condition 
            if kwargs.get('text_keyword'):
                conditions.append({"text_embedding": {"$text": {"$search": kwargs['text_keyword']}}})
            
            # If no conditions were added, return None
            if not conditions:
                return None
            
            # If only one condition, return it directly
            if len(conditions) == 1:
                return conditions[0]
            
            # If multiple conditions, combine them with $and
            return {"$and": conditions}
    
    def search(self, query, top_k=None, strategy='semantic', doc_title=None, docs_type=None, text_keyword=None):
        """"""
        top_k = top_k or self.default_top_k

        filters = self.build_filter(doc_title=doc_title, docs_type=docs_type, text_keyword=text_keyword)
        
        if strategy == 'semantic':
            return self.semantic_search(query=query, filters=filters, top_k=top_k)
    
    def semantic_search(self, query, top_k=1, filters=None):
        return self.vectorstore.similarity_search(
            query=query,
            k=top_k,
            filter=filters
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

    # Initialise search engine
    collection_name = "docsite-20240225"
    docsite_search = DocsiteSearch(collection_name=collection_name)
    results = docsite_search.search("Query for tasks in a given project")
    print(results)
    return results


if __name__ == "__main__":
    main()