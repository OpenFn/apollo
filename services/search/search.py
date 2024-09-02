import os
import json
from util import DictObj, createLogger
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

logger = createLogger("search")

class Payload(DictObj):
    query: str
    api_key: str

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)

        #Embedding model
        openai_ef = OpenAIEmbeddings(
        model="text-embedding-3-small", 
        api_key=data.api_key
        )

        zilliz_uri= os.getenv('ZILLIZ_URI')
        zilliz_token = os.getenv('ZILLIZ_TOKEN')
        print(f"Connecting to DB: {zilliz_uri}")

        #Connect to milvus
        client = MilvusClient(
        uri=zilliz_uri,
        token=zilliz_token
        )

        #Get embeddings for search
        logger.info("Encoding search string...")
        search_embeddings = [openai_ef.embed_query(data.query)]

        logger.info("Searching database for revelent info...")

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 16}}
        res = client.search(collection_name="openfn_docs",
        data=search_embeddings,
        limit=5,
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

        return documents    
    except Exception as e:
        logger.error(f"An error occurred during execution: {e}")
        raise