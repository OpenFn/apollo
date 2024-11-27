import os
from dotenv import load_dotenv
import anthropic
from search.search import Payload, validate_payload, connect_to_milvus, get_search_embeddings, search_database, extract_documents
from docsite_explainer.prompts import build_prompt

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZILLIZ_URI = os.getenv("ZILLIZ_CLOUD_URI")
ZILLIZ_TOKEN = os.getenv("ZILLIZ_CLOUD_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def query_llm(system_prompt, formatted_user_prompt, model="claude-3-5-sonnet-20241022", max_tokens=500):
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": formatted_user_prompt
                    }
                ]
            }
        ]
    )
    answer = message.content[0].text

    return answer

def explain_docs(input_text):

    # Set and validate database settings 
    settings_dict = {"api_key":OPENAI_API_KEY, "query":input_text, "partition_name":"normal_docs", "limit": 4}
    data = Payload(settings_dict)
    validate_payload(data)

    # Connect to Milvus database
    milvus_client = connect_to_milvus(db_name="openfn_docs")

    # Generate embeddings for the search query
    search_embeddings = get_search_embeddings(api_key=data.api_key, query=data.query)

    # Perform the search
    limit = int(data.limit)
    res = search_database(milvus_client, search_embeddings, data.partition_name, limit)

    # Extract documents from search results
    documents = extract_documents(res)

    # Collate llm input
    context_dict = {
        "input_text" : input_text,
        "context" : documents[0],
        "additional_context_a" : documents[1],
        "additional_context_b" : documents[2],
        "additional_context_c" : documents[3],
    }

    # Get formatted prompts
    system_prompt, formatted_user_prompt = build_prompt(context_dict)

    # Query llm with the prompts
    result = query_llm(system_prompt, formatted_user_prompt)

    return result


def main(data):

    input_text = data.get("text", "")

    result = explain_docs(input_text)
    print(f"Input query: {input_text}")
    print(f"Answer: {result}")

    return {
            "answer": result
        }

if __name__ == "__main__":
    main()