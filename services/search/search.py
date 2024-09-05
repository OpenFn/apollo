import os
import json
from openai import OpenAI
from util import DictObj, createLogger
from pymilvus import MilvusClient

logger = createLogger("search")

class Payload(DictObj):
    api_key: str
    query: str
    collection_name: str = "openfn_docs" 
    limit: int = 5  # Default limit value
    summarize: bool = False

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)

        # Validate the limit value
        if not (1 <= data.limit <= 15):
            raise ValueError("Limit must be between 1 and 15.")
        
        logger.info("Connecting to database...")
        zilliz_uri = os.getenv('ZILLIZ_URI')
        zilliz_token = os.getenv('ZILLIZ_TOKEN')

        # Connect to Milvus
        print(f"Connecting to DB: {zilliz_uri}")
        client = MilvusClient(
            uri=zilliz_uri,
            token=zilliz_token,
            db_name="openfn_docs"
        )

        embedding_client = OpenAI(api_key=data.api_key)

        # Get embeddings for search
        logger.info("Encoding search string...")
        response = embedding_client.embeddings.create(
            model="text-embedding-3-small", 
            input=data.query
        )
        search_embeddings = response.data[0].embedding

        logger.info("Searching database for relevant info...")

        search_params = {
            "metric_type": "L2",
            "params": {
                "nprobe": 16,        # Number of clusters to search in
                "radius": 1.2,       # Search radius threshold
                "level": 2           # Search precision level (1-3). Higher values yield more accurate results but slower performance.
                # "range_filter": 0.7 - Filters out vectors beyond this threshold
            }
        }
        
        res = client.search(
            collection_name=data.collection_name,
            data=[search_embeddings],
            limit=data.limit,
            search_params=search_params,
            output_fields=["text"]
        )

        logger.info("Extracting documents...")
        documents = []
        for hits in res:
            if isinstance(hits, str):
                hits = json.loads(hits)  # Parse string to list of dictionaries
            for hit in hits:
                logger.info("\n\n" + hit['entity']['text'] + "\n" + f"Distance: {hit['distance']}\n\n")
                documents.append(hit['entity']['text'])
                 
        return documents    
    except Exception as e:
        logger.error(f"An error occurred during execution: {e}")
        raise