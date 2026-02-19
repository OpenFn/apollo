import os
import json
import anthropic
from anthropic import (
    APIConnectionError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    UnprocessableEntityError,
    RateLimitError,
    InternalServerError,
)
import sentry_sdk
from util import ApolloError, create_logger
from search_docsite.search_docsite import DocsiteSearch
from .rag_config_loader import ConfigLoader
from streaming_util import StreamManager

logger = create_logger("job_chat.retrieve_docs")

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
                try:
                    search_results = search_docs(
                        search_queries,
                        top_k=config["top_k"],
                        threshold=config["threshold"]
                    )
                    search_results = list(set(search_results))
                    search_results_sections = list(set(result.metadata["doc_title"] for result in search_results))
                except Exception as e:
                    logger.error(f"Pinecone search failed: {e}")
                    sentry_sdk.capture_exception(e)
                    # Continue with empty results - chat can still work without docs
                    search_results = []
                    search_results_sections = []
        
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

    try:
        answer_parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}. Response text: {text[:200]}")
        raise ApolloError(
            500,
            "Failed to generate search queries - invalid response from AI service",
            type="INVALID_LLM_RESPONSE",
            details={"response_preview": text[:200]}
        )

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
    """Helper method to make LLM calls with error handling."""
    try:
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

        # Validate response has content
        if not message.content or len(message.content) == 0:
            raise ApolloError(500, "Empty response from AI service", type="EMPTY_LLM_RESPONSE")

        response_text = message.content[0].text
        if not response_text:
            raise ApolloError(500, "Empty text in AI service response", type="EMPTY_LLM_RESPONSE")

        return (response_text, message.usage.model_dump())

    except APIConnectionError as e:
        logger.error(f"API connection error during knowledge retrieval: {e}")
        details = {"cause": str(e.__cause__)} if e.__cause__ else {}
        raise ApolloError(
            503,
            "Unable to reach the AI service for documentation search",
            type="CONNECTION_ERROR",
            details=details,
        )
    except AuthenticationError as e:
        logger.error(f"Authentication error during knowledge retrieval: {e}")
        raise ApolloError(401, "Authentication failed with AI service", type="AUTH_ERROR")
    except RateLimitError as e:
        logger.error(f"Rate limit error during knowledge retrieval: {e}")
        retry_after = int(e.response.headers.get('retry-after', 60)) if hasattr(e, 'response') else 60
        raise ApolloError(
            429,
            "Rate limit exceeded for documentation search, please try again later",
            type="RATE_LIMIT",
            details={"retry_after": retry_after}
        )
    except BadRequestError as e:
        logger.error(f"Bad request error during knowledge retrieval: {e}")
        raise ApolloError(400, f"Invalid request to AI service: {str(e)}", type="BAD_REQUEST")
    except PermissionDeniedError as e:
        logger.error(f"Permission denied error during knowledge retrieval: {e}")
        raise ApolloError(403, "Not authorized to perform this action", type="FORBIDDEN")
    except NotFoundError as e:
        logger.error(f"Not found error during knowledge retrieval: {e}")
        raise ApolloError(404, "Resource not found", type="NOT_FOUND")
    except UnprocessableEntityError as e:
        logger.error(f"Unprocessable entity error during knowledge retrieval: {e}")
        raise ApolloError(422, str(e), type="INVALID_REQUEST")
    except InternalServerError as e:
        logger.error(f"Internal server error from AI service during knowledge retrieval: {e}")
        raise ApolloError(500, "The AI service encountered an error", type="PROVIDER_ERROR")
    except Exception as e:
        logger.error(f"Unexpected error during LLM call for knowledge retrieval: {str(e)}")
        raise ApolloError(500, f"Unexpected error during documentation search: {str(e)}", type="UNKNOWN_ERROR")