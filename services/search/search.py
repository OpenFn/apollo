import os
import json
from util import DictObj, createLogger
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient
from .utils import summarize_context

logger = createLogger("search")

class Payload(DictObj):
    query: str
    api_key: str
    summarize: bool = False
    limit: int = 5  # Default limit value
    collection_name: str = "openfn_docs" 

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)

        # Validate the limit value
        if not (1 <= data.limit <= 15):
            raise ValueError("Limit must be between 1 and 15.")

        # Embedding model
        openai_ef = OpenAIEmbeddings(
            model="text-embedding-3-small", 
            api_key=data.api_key
        )

        zilliz_uri = os.getenv('ZILLIZ_URI')
        zilliz_token = os.getenv('ZILLIZ_TOKEN')
        print(f"Connecting to DB: {zilliz_uri}")

        # Connect to Milvus
        client = MilvusClient(
            uri=zilliz_uri,
            token=zilliz_token,
            db_name="openfn_docs"
        )

        # Get embeddings for search
        logger.info("Encoding search string...")
        search_embeddings = openai_ef.embed_documents([data.query])

        logger.info("Searching database for relevant info...")

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        res = client.search(
            collection_name=data.collection_name,
            data=search_embeddings,
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
                documents.append(hit['entity']['text'])        

        if data.summarize:
            logger.info("Summarizing documents...")
            documents = summarize_context(api_key=data.api_key, context=documents, query=data.query)
                 
        return documents    
    except Exception as e:
        logger.error(f"An error occurred during execution: {e}")
        raise