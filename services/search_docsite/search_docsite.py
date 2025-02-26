import os
from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from util import create_logger, ApolloError
from embeddings.embeddings import SearchResult

logger = create_logger("DocsiteSearch")

class DocsiteSearch:
    """Initialise the docsite vectorstore and search it with optional metadata filters."""
    def __init__(self, collection_name, index_name="docsite", default_top_k=5, embeddings=OpenAIEmbeddings()):
        self.collection_name = collection_name
        self.index_client = index_name
        self.default_top_k = default_top_k
        self.vectorstore = PineconeVectorStore(index_name=index_name, namespace=collection_name, embedding=embeddings)
    
    def build_filter(self, **kwargs):
            conditions = []

            # Add exact match conditions
            if kwargs.get('doc_title'):
                conditions.append({"doc_title": {"$eq": kwargs['doc_title']}})
            

            if kwargs.get('docs_type'):
                conditions.append({"docs_type": {"$eq": kwargs['docs_type']}})
            
            # If no conditions were added, return None
            if not conditions:
                return None
            
            # If only one condition, return it directly
            if len(conditions) == 1:
                return conditions[0]
            
            # If multiple conditions, combine them with $and
            return {"$and": conditions}
    
    def search(self, query, top_k=None, strategy='semantic', doc_title=None, docs_type=None):
        """Search database with optional filters."""
        top_k = top_k or self.default_top_k

        filters = self.build_filter(doc_title=doc_title, docs_type=docs_type)
        logger.info("Metadata filters built")

        if strategy == 'semantic':
            return self.semantic_search(query=query, filters=filters, top_k=top_k)
    
    def semantic_search(self, query, top_k, filters=None):
        results = []
        retrieved_docs =  self.vectorstore.similarity_search(
            query=query,
            k=top_k,
            filter=filters
        )
        logger.info(f"Similar documents retreived: {len(retrieved_docs)}")
        retrieved_texts = [t.page_content for t in retrieved_docs]
        metadata_dicts = [t.metadata for t in retrieved_docs]

        for text, metadata in zip(retrieved_texts, metadata_dicts):
            results.append(SearchResult(text, metadata))

        return results


def main(data):
    logger.info("Starting...")

    required_fields = ["query", "collection_name"]

    missing = [field for field in required_fields if field not in data]
    
    if missing:
        logger.error(f"Missing required fields in data: {', '.join(missing)}")
        return

    index_params = {"collection_name": data["collection_name"]}
    search_params = {"query": data["query"]}

    # Add optional parameters
    optional_search_params = ["docs_type", "doc_title", "top_k", "strategy"]
    optional_index_params = ["index_name", "default_top_k", "embeddings"]

    for key in optional_search_params:
        if key in data:
            search_params[key] = data[key]

    for key in optional_index_params:
        if key in data:
            optional_index_params[key] = data[key]

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
    docsite_search = DocsiteSearch(**index_params)
    logger.info("Docsite database initialised")
    results = docsite_search.search(**search_params)
    
    return [result.to_json() for result in results]

if __name__ == "__main__":
    main()