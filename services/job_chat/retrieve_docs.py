import os
import json
import anthropic
from search_docsite import DocsiteSearch
from rag_config_loader import ConfigLoader

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
docsite_search = DocsiteSearch()

config_loader = ConfigLoader(config_path="rag.yaml", prompts_path="rag_prompts.yaml")
config = config_loader.config

def retrieve_knowledge(user_question, adaptor=None):
    """Use LLM calls and semantic search to retrieve documentation sections if needed."""
    user_context = format_context(adaptor)
    docs_decision = needs_docs(user_question, user_context)

    search_results = []
    search_queries = []
    if docs_decision.lower().startswith("true"):
        search_queries = generate_queries(user_question, user_context="")
        search_results = search_docs(
            search_queries, 
            top_k=config["top_k"], 
            threshold=config["threshold"]
        )
    
    results = {"search_results": search_results, "search_queries": search_queries}
    
    return results

def needs_docs(user_question, user_context=""):
    """Use LLM to decide whether the question requires consulting documentation."""
    formatted_user_prompt = config_loader.get_prompt(
        "needs_docs_user_prompt",
        user_context=user_context, 
        user_question=user_question
    )
    
    response_text = call_llm(
        model=config["llm_search_decision"],
        temperature=config["temperature"],
        system_prompt=config_loader.prompts["prompts"]["needs_docs_system_prompt"],
        user_prompt=formatted_user_prompt
    )
    
    return response_text

def generate_queries(user_question, user_context=""):
    """Generate document search queries based on the user question."""
    formatted_user_prompt = config_loader.get_prompt(
        "search_docs_user_prompt",
        user_context=user_context, 
        user_question=user_question
    )
    
    text = call_llm(
        model=config["llm_retrieval"],
        temperature=config["temperature"],
        system_prompt=config_loader.prompts["prompts"]["search_docs_system_prompt"],
        user_prompt=formatted_user_prompt
    )
    
    answer_parsed = json.loads(text)
    
    return answer_parsed

def search_docs(search_queries, top_k, threshold):
    """Search the docsite vector store using search queries."""
    search_results = []
    for q in search_queries:
        query_search_result = docsite_search.search(
            q.get("query"), 
            top_k=top_k, 
            threshold=threshold, 
            docs_type=q.get("doc_type")
        )
        search_results.extend(query_search_result)
    
    return search_results

def format_context(adaptor):
    """Optionally add more context about the user's job for the LLM."""
    return f"For context, the user is using the {adaptor} adaptor. " if adaptor else ""

def call_llm(model, temperature, system_prompt, user_prompt):
    """Helper method to make LLM calls."""
    message = client.messages.create(
        model=model,
        max_tokens=500,
        temperature=temperature,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt
                    }
                ]
            }
        ]
    )
    return message.content[0].text