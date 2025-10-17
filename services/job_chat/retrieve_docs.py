import os
import json
import anthropic
import sentry_sdk
from search_docsite.search_docsite import DocsiteSearch
from .rag_config_loader import ConfigLoader
from streaming_util import StreamManager

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "rag.yaml")
prompts_path = os.path.join(base_dir, "rag_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

def get_client(api_key=None):
    """Get Anthropic client with provided API key or environment variable."""
    key = api_key or ANTHROPIC_API_KEY
    if not key:
        raise ValueError("API key must be provided either as parameter or in ANTHROPIC_API_KEY environment variable")
    return anthropic.Anthropic(api_key=key)


def retrieve_knowledge(content, history, code="", adaptor="", api_key=None):
    """
    Retrieve relevant documentation sections based on user's question.
    
    Uses LLM to determine if documentation search is needed, then generates
    search queries and retrieves matching documentation sections.
    
    :param content: The question or message from the user
    :param adaptor: Optional adaptor added as context to the question
    :return: Dictionary containing:
        :search_results: List of search result objects
        :search_results_sections: List of document titles from search results
        :search_queries: List of generated search queries
        :config_version: Version of the configuration used
        :prompts_version: Version of the prompts used
    """
    with sentry_sdk.start_span(description="retrieve_knowledge"):
        client = get_client(api_key)

        user_context = format_context(adaptor, code, history)
        with sentry_sdk.start_span(description="needs_docs_decision"):
            docs_decision, needs_docs_usage = needs_docs(content, client, user_context)

        search_results = []
        search_results_sections = []
        search_queries = []
        generate_queries_usage = {}

        if docs_decision.lower().startswith("true"):
            with sentry_sdk.start_span(description="generate_search_queries"):
                search_queries, generate_queries_usage = generate_queries(content, client, user_context)
            with sentry_sdk.start_span(description="search_documentation"):
                search_results = search_docs(
                    search_queries, 
                    top_k=config["top_k"], 
                    threshold=config["threshold"]
                )
                search_results = list(set(search_results))
                search_results_sections = list(set(result.metadata["doc_title"] for result in search_results))
        
        results = {
            "search_results": [s.to_json() for s in search_results],
            "search_results_sections": search_results_sections,
            "search_queries": search_queries,
            "config_version": config.get("config_version"),
            "prompts_version": config.get("prompts_version"),
            "usage": {
                "needs_docs": needs_docs_usage,
                "generate_queries": generate_queries_usage
            }
        }
        
        return results

def needs_docs(content, client, user_context=""):
    """Use LLM to decide whether the question requires consulting documentation."""
    formatted_user_prompt = config_loader.get_prompt(
        "needs_docs_user_prompt",
        user_context=user_context, 
        user_question=content
    )
    
    response_text, usage = call_llm(
        model=config["llm_search_decision"],
        temperature=config["temperature"],
        system_prompt=config_loader.prompts["prompts"]["needs_docs_system_prompt"],
        user_prompt=formatted_user_prompt,
        client=client
    )
    
    return (response_text, usage)

def generate_queries(content, client, user_context=""):
    """Generate document search queries based on the user question."""
    formatted_user_prompt = config_loader.get_prompt(
        "search_docs_user_prompt",
        user_context=user_context, 
        user_question=content
    )
    
    text, usage = call_llm(
        model=config["llm_retrieval"],
        temperature=config["temperature"],
        system_prompt=config_loader.prompts["prompts"]["search_docs_system_prompt"],
        user_prompt=formatted_user_prompt,
        client=client
    )
    
    answer_parsed = json.loads(text)

    if len(answer_parsed) >= 4:
        answer_parsed = answer_parsed[:4]
    
    return (answer_parsed, usage)

def search_docs(search_queries, top_k, threshold):
    """Search the docsite vector store using search queries."""
    docsite_search = DocsiteSearch()
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

def format_context(adaptor, code, history):
    """Optionally add more context about the user's job for the LLM."""
    formatted_text = ""
    
    if adaptor:
        formatted_text += f"For context, the user is using the {adaptor} adaptor. "
    
    if code:
        formatted_text += f"Here is the user's code:\n\n {code}\n\n "
    
    if history:
        formatted_text += f"Here is the conversation history: {history}.\n "
    
    return formatted_text

def call_llm(model, temperature, system_prompt, user_prompt, client):
    """Helper method to make LLM calls."""
    message = client.messages.create(
        model=model,
        max_tokens=1024,
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
    return (message.content[0].text, message.usage.model_dump())