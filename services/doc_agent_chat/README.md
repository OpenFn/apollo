# doc_agent_chat

Agentic chat service (Claude Sonnet 4.5) with document search capabilities.

## Input

```json
{
  "content": "What are the key findings?",
  "context": {
    "project_id": "project123",
    "project_name": "Research Project",
    "documents": [
      {
        "uuid": "doc-uuid-1",
        "title": "Paper 1",
        "description": "First research paper"
      }
    ]
  },
  "history": [
    {"role": "user", "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ]
}
```

## Output

```json
{
  "response": "Based on the documents...",
  "history": [...],
  "usage": {...},
  "citations": [
    {
      "type": "document",
      "document_index": 0,
      "start": 45,
      "end": 120,
      "text": "cited text"
    }
  ],
  "meta": {
    "tool_calls": [...],
    "search_results": [...]
  }
}
```

## Usage

```bash
bun py doc_agent_chat input.json
```

## Notes

- Agent decides when to search documents via tool calling (up to 10 calls per turn)
- Searches Pinecone filtered by project_id for security
- Returns responses with citations (document index, character positions, quoted text)
- Supports multi-turn conversations with history
