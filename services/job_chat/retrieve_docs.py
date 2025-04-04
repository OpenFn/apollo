import os
import json
import anthropic
from search_docsite import DocsiteSearch
from rag_config_loader import ConfigLoader

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

config_loader = ConfigLoader(config_path="rag.yaml", prompts_path="rag_prompts.yaml")
config = config_loader.config

def retrieve_knowledge(content, history, code="", adaptor=""):
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

    user_context = format_context(adaptor, code, history)
    docs_decision, needs_docs_usage = needs_docs(content, user_context)

    search_results = []
    search_results_sections = []
    search_queries = []
    generate_queries_usage = None

    if docs_decision.lower().startswith("true"):
        search_queries, generate_queries_usage = generate_queries(content, user_context)
        search_results = search_docs(
            search_queries, 
            top_k=config["top_k"], 
            threshold=config["threshold"]
        )
        search_results = list(set(search_results))
        search_results_sections = list(set(result.metadata["doc_title"] for result in search_results))
    
    results = {
        "search_results": search_results,
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

def needs_docs(content, user_context=""):
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
        user_prompt=formatted_user_prompt
    )
    
    return (response_text, usage)

def generate_queries(content, user_context=""):
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
        user_prompt=formatted_user_prompt
    )
    
    answer_parsed = json.loads(text)

    if len(answer_parsed) >= 4:
        answer_parsed = answer_parsed[:4]
    
    return (answer_parsed, usage)

def search_docs(search_queries, top_k, threshold):
    """Search the docsite vector store using search queries."""
    docsite_search = DocsiteSearch(collection_name="docsite-20250225") #TODO remove
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
    return (message.content[0].text, message.usage)