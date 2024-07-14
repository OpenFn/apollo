import os
import json
from util import DictObj, createLogger
from pymilvus import MilvusClient, model

logger = createLogger("search")

class Payload(DictObj):
    query: str
    api_key: str

def main(dataDict) -> str:
    try:
        data = Payload(dataDict)

        #Embedding model
        openai_ef = model.dense.OpenAIEmbeddingFunction(
        model_name='text-embedding-ada-002',
        api_key=data.api_key,
        )

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
        search_embeddings = openai_ef.encode_documents([data.query])

        logger.info("Searching database for revelent info...")

        search_params = {"metric_type": "L2", "params": {"nprobe": 16}}
        res = client.search(collection_name="apollo_sample",
        data=search_embeddings,
        limit=20, 
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