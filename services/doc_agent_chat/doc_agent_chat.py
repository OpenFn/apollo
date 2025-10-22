import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from anthropic import Anthropic
from dotenv import load_dotenv
from util import create_logger, ApolloError
from doc_agent_chat.doc_search import DocSearch
from doc_agent_chat.prompt import build_system_prompt

logger = create_logger("doc_agent_chat")

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 16384
MAX_TOOL_CALLS = 10
SEARCH_TOP_K = 5
SEARCH_THRESHOLD = 0.7


@dataclass
class Payload:
    content: str
    context: dict
    history: Optional[List[Dict[str, str]]] = None
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        if "content" not in data:
            raise ValueError("'content' is required")
        if "context" not in data:
            raise ValueError("'context' is required")

        context = data["context"]
        required_context_fields = ["project_id", "project_name", "documents"]
        for field in required_context_fields:
            if field not in context:
                raise ValueError(f"'context.{field}' is required")

        return cls(
            content=data["content"],
            context=context,
            history=data.get("history", []),
            api_key=data.get("api_key")
        )


def main(data: dict) -> dict:
    try:
        logger.info("Starting doc agent chat...")
        payload = Payload.from_dict(data)

        load_dotenv(override=True)
        ANTHROPIC_API_KEY = payload.api_key or os.environ.get('ANTHROPIC_API_KEY')
        OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
        PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')

        missing_keys = []
        if not ANTHROPIC_API_KEY:
            missing_keys.append("ANTHROPIC_API_KEY")
        if not OPENAI_API_KEY:
            missing_keys.append("OPENAI_API_KEY")
        if not PINECONE_API_KEY:
            missing_keys.append("PINECONE_API_KEY")

        if missing_keys:
            msg = f"Missing API keys: {', '.join(missing_keys)}"
            logger.error(msg)
            raise ApolloError(500, msg, type="MISSING_API_KEY")

        # Initialize search
        doc_search = DocSearch(
            project_id=payload.context["project_id"],
            available_doc_uuids=[doc["uuid"] for doc in payload.context["documents"]],
            index_name="doc_agent"
        )

        # Build system prompt
        system_prompt = build_system_prompt(payload.context)

        # Initialize Anthropic client
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        # Define search tool
        tools = [
            {
                "name": "search_documents",
                "description": "Search through project documents using semantic similarity. You can optionally filter by specific document UUIDs to search only within those documents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query text to find relevant document chunks"
                        },
                        "document_uuids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: Array of document UUIDs to filter the search. If not provided, searches all available documents."
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

        # Agentic loop
        messages = payload.history.copy() if payload.history else []
        messages.append({"role": "user", "content": payload.content})

        tool_calls_metadata = []
        all_search_results = []
        total_usage = {}

        for iteration in range(MAX_TOOL_CALLS):
            logger.info(f"Agentic loop iteration {iteration + 1}")

            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=tools
            )

            # Track usage
            if hasattr(response, "usage"):
                usage = response.usage.model_dump()
                for key, value in usage.items():
                    total_usage[key] = total_usage.get(key, 0) + value

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Agent finished
                logger.info("Agent finished naturally")
                final_response = _extract_text_response(response)
                messages.append({"role": "assistant", "content": response.content})
                break

            elif response.stop_reason == "tool_use":
                # Execute tools
                logger.info("Agent requested tool use")
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"Executing tool: {block.name}")

                        if block.name == "search_documents":
                            # Execute search
                            query = block.input.get("query")
                            document_uuids = block.input.get("document_uuids")

                            search_results = doc_search.search(
                                query=query,
                                document_uuids=document_uuids,
                                top_k=SEARCH_TOP_K,
                                threshold=SEARCH_THRESHOLD
                            )

                            # Track metadata
                            tool_calls_metadata.append({
                                "tool": "search_documents",
                                "input": {"query": query, "document_uuids": document_uuids},
                                "results_count": len(search_results)
                            })
                            all_search_results.extend(search_results)

                            # Format results as string
                            results_text = _format_search_results(search_results)

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": results_text
                            })

                # Add assistant message and tool results to conversation
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            else:
                # max_tokens or other stop reason
                logger.info(f"Stopped due to: {response.stop_reason}")
                final_response = _extract_text_response(response)
                messages.append({"role": "assistant", "content": response.content})
                break
        else:
            # Hit max iterations
            logger.warning("Hit max tool call iterations")
            final_response = _extract_text_response(response)
            messages.append({"role": "assistant", "content": response.content})

        # Build response
        return {
            "response": final_response,
            "history": messages,
            "usage": total_usage,
            "meta": {
                "tool_calls": tool_calls_metadata,
                "search_results": [r.to_json() for r in all_search_results]
            }
        }

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except Exception as e:
        logger.error(f"Error in doc agent chat: {str(e)}")
        raise ApolloError(500, str(e), type="INTERNAL_ERROR")


def _extract_text_response(response) -> str:
    """Extract text from response content blocks."""
    text_parts = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
    return "\n\n".join(text_parts)


def _format_search_results(results: List) -> str:
    """Format search results as a text string for the LLM."""
    if not results:
        return "No results found."

    formatted = "Search Results:\n\n"
    for i, result in enumerate(results, 1):
        formatted += f"[Result {i}]\n"
        formatted += f"Document: {result.metadata.get('doc_title', 'Unknown')}\n"
        formatted += f"Score: {result.score:.3f}\n"
        formatted += f"Content: {result.text}\n\n"

    return formatted


if __name__ == "__main__":
    main()
