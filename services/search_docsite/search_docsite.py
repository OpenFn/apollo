import os
from dotenv import load_dotenv
from langchain_pinecone import PineconeVectorStore
from langchain_openai import OpenAIEmbeddings
from util import create_logger, ApolloError
from embeddings.embeddings import SearchResult

logger = create_logger("DocsiteSearch")

class DocsiteSearch:
    """
    Initialize the docsite vectorstore and search it with optional metadata filters.
    
    :param collection_name: Vectorstore collection name (namespace) to store documents
    :param index_name: Vectostore index name (default: docsite)
    :param default_top_k: Default number of results to return (default: 5)
    :param embeddings: LangChain embedding type (default: OpenAIEmbeddings())
    """
    def __init__(self, collection_name, index_name="docsite", default_top_k=5, embeddings=OpenAIEmbeddings()):
        self.collection_name = collection_name
        self.index_client = index_name
        self.default_top_k = default_top_k
        self.vectorstore = PineconeVectorStore(index_name=index_name, namespace=collection_name, embedding=embeddings)
    
    def _build_filter(self, **kwargs):
            """Build filter conditions to search the vectorstore."""
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
    
    def _semantic_search(self, query, top_k=None, threshold=None, filters=None):
        """Search the vectorstore using semantic search."""
        if top_k is None and threshold is None:
            top_k = self.default_top_k
        
        # Always set a reasonable maximum to avoid potential performance issues
        max_k = top_k or 100  # Limit to 100 if using threshold-only
        
        # Get scored results - we need scores for threshold filtering
        scored_docs = self.vectorstore.similarity_search_with_score(
            query=query,
            k=max_k,
            filter=filters
        )
        
        logger.info(f"Similar documents retrieved: {len(scored_docs)}")
        
        results = []
        for doc, score in scored_docs:
            # If threshold is set, only include documents with score >= threshold
            # Note: Pinecone scores are cosine similarity (higher is better)
            if threshold is not None and score < threshold:
                continue
                
            # If we've reached top_k docs and no threshold is set, stop
            if top_k is not None and len(results) >= top_k and threshold is None:
                break
                
            results.append(SearchResult(doc.page_content, doc.metadata, score))
            
        logger.info(f"Filtered to {len(results)} results")
        return results
    
    def search(self, query, top_k=None, threshold=None, strategy='semantic', doc_title=None, docs_type=None):
        """
        Search database with optional filters.

        :param query: Search query string
        :param top_k: Number of results to return
        :param strategy: Search strategy (default: 'semantic')
        :param doc_title: Filter by document title
        :param docs_type: Filter by document type
        :return: List of SearchResult objects
        """
        filters = self._build_filter(doc_title=doc_title, docs_type=docs_type)
        logger.info("Metadata filters built")

        if strategy == 'semantic':
            return self._semantic_search(query=query, top_k=top_k, threshold=threshold, filters=filters)


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
    optional_search_params = ["docs_type", "doc_title", "top_k", "threshold", "strategy"]
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