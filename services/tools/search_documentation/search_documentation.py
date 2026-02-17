"""
Documentation search service - standalone tool for searching OpenFn documentation.

Can be called:
1. As a standalone service via entry.py: bun py tools/search_documentation
2. As a tool by supervisor via search_documentation_tool()
"""
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

# Import utilities from services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from util import create_logger, ApolloError
from search_docsite.search_docsite import DocsiteSearch

logger = create_logger(__name__)


@dataclass
class SearchPayload:
    """Input payload for documentation search."""
    query: str
    num_results: int = 5

    @classmethod
    def from_dict(cls, data: Dict) -> "SearchPayload":
        """Validate and create payload from dict."""
        if "query" not in data:
            raise ApolloError(400, "query is required")

        return cls(
            query=data["query"],
            num_results=data.get("num_results", 5)
        )


def _search_implementation(query: str, num_results: int) -> Dict:
    """
    Core search implementation - shared by both calling patterns.

    Returns structured dict with search results.
    """
    logger.info(f"Searching documentation for: {query[:100]}...")

    # Initialize docsite search
    docsite_search = DocsiteSearch()

    # Search with threshold for quality results
    search_results = docsite_search.search(
        query=query,
        top_k=num_results,
        threshold=0.7,  # Only return relevant results
        strategy='semantic'
    )

    logger.info(f"Found {len(search_results)} documentation results")

    # Return structured results
    return {
        "query": query,
        "num_results": len(search_results),
        "results": [
            {
                "title": r.metadata.get("doc_title", "Unknown"),
                "content": r.text[:500],
                "score": r.score,
                "url": r.metadata.get("url", "")
            }
            for r in search_results
        ]
    }


def main(data: Dict) -> Dict:
    """
    Entry.py service pattern - returns structured dict.

    Usage:
        bun py tools/search_documentation input.json
    """
    try:
        payload = SearchPayload.from_dict(data)
        result = _search_implementation(payload.query, payload.num_results)
        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error in search_documentation service")
        raise ApolloError(500, f"Documentation search failed: {str(e)}")


def search_documentation_tool(tool_input: Dict) -> str:
    """
    Anthropic tool calling pattern - returns formatted string for LLM.

    This is called by the supervisor when it uses the search_documentation tool.
    """
    try:
        query = tool_input.get("query")
        num_results = tool_input.get("num_results", 5)

        if not query:
            raise ApolloError(400, "query is required for documentation search")

        # Use shared implementation
        result = _search_implementation(query, num_results)

        # Format for LLM consumption
        if result["num_results"] == 0:
            return f"""No relevant documentation found for query: "{query}"

You may want to try:
1. Rephrasing the query
2. Using more general terms
3. Calling the tool again with a different query"""

        # Build formatted response
        formatted_results = f"""Found {result['num_results']} relevant documentation sections for: "{query}"

"""

        for i, r in enumerate(result["results"], 1):
            formatted_results += f"""--- Result {i} (relevance: {r['score']:.2f}) ---
Title: {r['title']}
Content: {r['content']}...
URL: {r['url']}

"""

        formatted_results += f"""
These documentation sections can help answer the user's question.
You can now synthesize this information into a helpful response."""

        return formatted_results

    except Exception as e:
        logger.exception("Error in search_documentation tool")
        raise ApolloError(500, f"Documentation search failed: {str(e)}")
