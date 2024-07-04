import os
import requests
import json
from util import DictObj, createLogger
from pymilvus import MilvusClient

logger = createLogger("search")

def embedding_query(texts):
    try:
        #Request parameters
        model_id = "sentence-transformers/all-MiniLM-L6-v2"
        api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_id}"

        hf_token = os.getenv("HF_EMBEDDING_TOKEN")
        headers = {"Authorization": f"Bearer {hf_token}"}

        print(f"Sending request to {hf_token}")

        response = requests.post(api_url, headers=headers, json={"inputs": texts, "options":{"wait_for_model":True}})  
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"Request to Hugging Face API failed, try again!")
        raise

class Payload(DictObj):
    search_string: str

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)

        milvus_uri= os.getenv('MILVUS_URI')
        milvus_token = os.getenv('MILVUS_TOKEN')
        print(f"Connecting to DB: {milvus_uri}")

        #Connect to milvus
        client = MilvusClient(
        uri=milvus_uri,
        token=milvus_token,
        db_name="apollo_db"
        )

        #Get embeddings for search
        logger.info("Encoding search string...")
        search_embeddings = embedding_query([data.search_string])

        logger.info("Searching database for revelent info...")

        search_params = {"metric_type": "L2", "params": {"nprobe": 16}}
        res = client.search(collection_name="apollo_sample",
        data=search_embeddings,
        limit=10, 
        search_params=search_params,
        output_fields=["text"]
        )

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
    



    