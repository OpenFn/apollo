from typing import Optional, List

TOOL_DEFINITIONS = [
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


def search_documents(doc_search, query: str, document_uuids: Optional[List[str]] = None, top_k: int = 5, threshold: float = 0.7):
    """Search through project documents."""
    return doc_search.search(
        query=query,
        document_uuids=document_uuids,
        top_k=top_k,
        threshold=threshold
    )


def format_search_results(results: List) -> str:
    """Format search results as text for the LLM."""
    if not results:
        return "No results found."

    formatted = "Search Results:\n\n"
    for i, result in enumerate(results, 1):
        formatted += f"[Result {i}]\n"
        formatted += f"Document: {result.metadata.get('doc_title', 'Unknown')}\n"
        formatted += f"Score: {result.score:.3f}\n"
        formatted += f"Content: {result.text}\n\n"

    return formatted
