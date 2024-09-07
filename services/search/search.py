import json
from openai import OpenAI
from util import DictObj, createLogger
from pymilvus import MilvusClient
from .utils import connect_to_milvus

logger = createLogger("search")

class Payload(DictObj):
    api_key: str
    query: str
    partition_name: str = None  # Optional partition_name. Helps distinguish between normal docs and adaptor data
    limit: int = 5  # Default limit value

def validate_payload(data: Payload):
    """
    Validates the payload data.

    :param data: Payload object containing the input data
    :raises ValueError: If any validation checks fail
    """
    if not (1 <= data.limit <= 15):
        raise ValueError("Limit must be between 1 and 15.")
    if not data.api_key:
        raise ValueError("API key is missing.")
    if not data.query:
        raise ValueError("Query string is missing.")


def get_search_embeddings(api_key: str, query: str) -> list:
    """
    Generates embeddings for the query using OpenAI's embedding API.

    :param api_key: OpenAI API key
    :param query: Query string to be embedded
    :return: List of embeddings
    :raises Exception: If the embedding API call fails
    """
    try:
        embedding_client = OpenAI(api_key=api_key)
        logger.info("Encoding search string...")
        response = embedding_client.embeddings.create(
            model="text-embedding-3-small", 
            input=query
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        raise

def search_database(client: MilvusClient, search_embeddings: list, partition_name: str, limit: int) -> list:
    """
    Searches the Milvus database for relevant documents using embeddings.

    :param client: MilvusClient instance
    :param search_embeddings: Embeddings for the search query
    :param partition_name: Optional partition name for partitioned search
    :param limit: Maximum number of results to return
    :return: List of search results
    """
    search_params = {
        "metric_type": "L2",
        "params": {
            "nprobe": 16,  # Number of clusters to search in
            "radius": 1.2,  # Search radius threshold
            "level": 2      # Search precision level (1-3). Higher values yield more accurate results but slower performance.
        }
    }

    logger.info(f"Searching database with limit={limit}...")
    try:
        if partition_name:
            logger.info(f"Searching within partition: {partition_name}")
            res = client.search(
                collection_name="openfn_docs",
                data=[search_embeddings],
                limit=limit,
                search_params=search_params,
                partition_names=[partition_name],  # Search within specified partition
                output_fields=["text"]
            )
        else:
            logger.info("Searching entire collection")
            res = client.search(
                collection_name="openfn_docs",  # Search entire collection
                data=[search_embeddings],
                limit=limit,
                search_params=search_params,
                output_fields=["text"]
            )

        return res
    except Exception as e:
        logger.error(f"Database search failed: {e}")
        raise

def extract_documents(res) -> list:
    """
    Extracts the document texts from the search results.

    :param res: Search results from Milvus
    :return: List of document texts
    """
    documents = []
    logger.info("Extracting documents from search results...")

    for hits in res:
        if isinstance(hits, str):
            hits = json.loads(hits)  # Parse string to list of dictionaries

        for hit in hits:
            text = hit['entity']['text']
            distance = hit['distance']
            print(f"Distance: {distance}\n{text}\n")
            documents.append(text)

    return documents

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)
        validate_payload(data)

        # Connect to Milvus database
        client = connect_to_milvus()

        # Generate embeddings for the search query
        search_embeddings = get_search_embeddings(api_key=data.api_key, query=data.query)

        # Perform the search
        res = search_database(client, search_embeddings, data.partition_name, data.limit)

        # Extract documents from search results
        documents = extract_documents(res)

        return documents
    except Exception as e:
        logger.error(f"An error occurred during execution: {e}")
        raise