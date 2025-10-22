import os
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from util import create_logger
from doc_agent_chat.doc_search import DocSearch
from doc_agent_chat.prompt import build_system_prompt
from doc_agent_chat.tools import TOOL_DEFINITIONS, search_documents, format_search_results
from doc_agent_chat.config_loader import ConfigLoader

logger = create_logger("agent")

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "config.yaml")
config_loader = ConfigLoader(config_path=config_path)
config = config_loader.config


class Agent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")

        self.client = Anthropic(api_key=self.api_key)
        self.model = config.get("model", "claude-sonnet-4-5-20250929")
        self.max_tokens = config.get("max_tokens", 16384)
        self.max_tool_calls = config.get("max_tool_calls", 10)
        self.search_top_k = config.get("search_top_k", 5)
        self.search_threshold = config.get("search_threshold", 0.7)

    def run(
        self,
        content: str,
        context: dict,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Run the agent with the given content and context."""
        doc_search = DocSearch(
            project_id=context["project_id"],
            available_doc_uuids=[doc["uuid"] for doc in context["documents"]],
            index_name="doc_agent"
        )

        system_prompt = build_system_prompt(context)
        messages = history.copy() if history else []
        messages.append({"role": "user", "content": content})

        tool_calls_metadata = []
        all_search_results = []
        total_usage = {}

        for iteration in range(self.max_tool_calls):
            logger.info(f"Agentic loop iteration {iteration + 1}")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=TOOL_DEFINITIONS
            )

            if hasattr(response, "usage"):
                usage = response.usage.model_dump()
                for key, value in usage.items():
                    total_usage[key] = total_usage.get(key, 0) + value

            if response.stop_reason == "end_turn":
                logger.info("Agent finished naturally")
                final_response = self._extract_text(response)
                messages.append({"role": "assistant", "content": response.content})
                break

            elif response.stop_reason == "tool_use":
                logger.info("Agent requested tool use")
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use" and block.name == "search_documents":
                        logger.info(f"Executing tool: {block.name}")

                        query = block.input.get("query")
                        document_uuids = block.input.get("document_uuids")

                        search_results = search_documents(
                            doc_search=doc_search,
                            query=query,
                            document_uuids=document_uuids,
                            top_k=self.search_top_k,
                            threshold=self.search_threshold
                        )

                        tool_calls_metadata.append({
                            "tool": "search_documents",
                            "input": {"query": query, "document_uuids": document_uuids},
                            "results_count": len(search_results)
                        })
                        all_search_results.extend(search_results)

                        results_text = format_search_results(search_results)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": results_text
                        })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

            else:
                logger.info(f"Stopped due to: {response.stop_reason}")
                final_response = self._extract_text(response)
                messages.append({"role": "assistant", "content": response.content})
                break
        else:
            logger.warning("Hit max tool call iterations")
            final_response = self._extract_text(response)
            messages.append({"role": "assistant", "content": response.content})

        return {
            "response": final_response,
            "history": messages,
            "usage": total_usage,
            "meta": {
                "tool_calls": tool_calls_metadata,
                "search_results": [r.to_json() for r in all_search_results]
            }
        }

    def _extract_text(self, response) -> str:
        """Extract text from response content blocks."""
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "\n\n".join(text_parts)
