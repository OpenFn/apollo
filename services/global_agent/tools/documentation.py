"""
Documentation search tool for the supervisor agent.

Simplified version of job_chat's retrieve_docs - just searches the docsite.
The supervisor decides when to search (no needs_docs LLM call).
"""
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Import utilities from parent services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from util import create_logger, ApolloError
from search_docsite.search_docsite import DocsiteSearch

logger = create_logger(__name__)


def search_documentation(tool_input: Dict) -> str:
    """
    Search OpenFn documentation using Pinecone vector store.

    This is called by the supervisor when it uses the search_documentation tool.

    Args:
        tool_input: Dictionary with 'query' and optional 'num_results'

    Returns:
        Formatted string with search results for the LLM to read
    """
    try:
        query = tool_input.get("query")
        num_results = tool_input.get("num_results", 5)

        if not query:
            raise ApolloError(400, "query is required for documentation search")

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

        # Format results for LLM
        if not search_results:
            return f"""No relevant documentation found for query: "{query}"

You may want to try:
1. Rephrasing the query
2. Using more general terms
3. Calling the tool again with a different query"""

        # Build formatted response
        formatted_results = f"""Found {len(search_results)} relevant documentation sections for: "{query}"

"""

        for i, result in enumerate(search_results, 1):
            title = result.metadata.get("doc_title", "Unknown")
            content = result.text[:500]  # Limit content length (note: SearchResult uses 'text' not 'content')
            score = result.score
            url = result.metadata.get("url", "")

            formatted_results += f"""--- Result {i} (relevance: {score:.2f}) ---
Title: {title}
Content: {content}...
URL: {url}

"""

        formatted_results += f"""
These documentation sections can help answer the user's question.
You can now synthesize this information into a helpful response."""

        return formatted_results

    except Exception as e:
        logger.exception("Error in search_documentation tool")
        raise ApolloError(500, f"Documentation search failed: {str(e)}")
