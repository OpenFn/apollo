import os
import json
from openai import OpenAI
from pinecone import Pinecone
from anthropic import Anthropic
from util import create_logger

logger = create_logger("status")

def test_openai_key(api_key):
    try:
        OpenAI(api_key=api_key).models.list()
        return True
    except Exception:
        return False

def test_pinecone_key(api_key):
    try:
        Pinecone(api_key=api_key).list_indexes()
        return True
    except Exception:
        return False

def test_anthropic_key(api_key):
    try:
        Anthropic(api_key=api_key).models.list()
        return True
    except Exception:
        return False

def main(data):
    status = {
        "openai": "working" if test_openai_key(os.getenv('OPENAI_API_KEY')) else "not working",
        "pinecone": "working" if test_pinecone_key(os.getenv('PINECONE_API_KEY')) else "not working",
        "anthropic": "working" if test_anthropic_key(os.getenv('ANTHROPIC_API_KEY')) else "not working"
    }

    logger.info(f"API Keys status: {json.dumps(status)}")
    return json.dumps(status)

if __name__ == "__main__":
    print(main(None))