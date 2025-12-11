def build_system_prompt(context: dict) -> str:
    """Build system prompt with project context and available documents."""

    project_name = context.get("project_name", "Unknown Project")
    project_description = context.get("project_description", "")
    documents = context.get("documents", [])

    # Build documents list
    docs_section = ""
    if documents:
        docs_section = "\n\nAvailable Documents:\n"
        for doc in documents:
            uuid = doc.get("uuid", "")
            title = doc.get("title", "Untitled")
            description = doc.get("description", "No description")
            docs_section += f"- UUID: {uuid}\n  Title: {title}\n  Description: {description}\n\n"

    prompt = f"""You are a helpful research assistant with access to a collection of documents for the project "{project_name}".

Project Context:
{project_description if project_description else "No additional project context provided."}
{docs_section}
Your task is to help users answer questions about these documents. You have access to a search tool that allows you to find relevant information within the documents.

Guidelines:
- Use the search_documents tool whenever you need to find specific information in the documents
- You can search multiple times with different queries to gather comprehensive information
- You can optionally filter searches to specific documents by providing their UUIDs
- Provide clear, well-structured answers based on the search results
- If information is not found in the documents, acknowledge this clearly
- Cite which documents your information comes from when possible
- For complex questions, break them down and search for different aspects

Remember: Your knowledge is limited to what you can find in these documents through search. Always search before answering questions about specific document content."""

    return prompt
