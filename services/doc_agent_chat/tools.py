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


def format_search_results_as_documents(results: List) -> List[dict]:
    """Format search results as Claude document content blocks with citations enabled."""
    if not results:
        return []

    documents = []
    for result in results:
        doc_title = result.metadata.get('doc_title', 'Unknown')
        user_description = result.metadata.get('user_description', '')

        # Build context: doc_title + user_description if available
        context = f"From document: {doc_title}"
        if user_description:
            context += f" - {user_description}"

        documents.append({
            "type": "document",
            "source": {
                "type": "text",
                "media_type": "text/plain",
                "data": result.text
            },
            "title": doc_title,
            "context": context,
            "citations": {"enabled": True}
        })

    return documents
