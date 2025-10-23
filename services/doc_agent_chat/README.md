# doc_agent_chat

Agentic chat service with document search capabilities.

## Overview

This service provides an AI agent (Claude Sonnet 4.5) that can search through uploaded documents to answer user questions. The agent uses tool calling to decide when and how to search documents, supporting multi-turn conversations with up to 10 tool calls per turn.

## Input

```json
{
  "content": "What are the key findings in the research papers?",
  "history": [
    {"role": "user", "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ],
  "context": {
    "project_id": "project123",
    "project_name": "Research Project",
    "project_description": "A collection of research papers on AI",
    "documents": [
      {
        "uuid": "doc-uuid-1",
        "title": "Paper 1",
        "description": "First research paper"
      },
      {
        "uuid": "doc-uuid-2",
        "title": "Paper 2",
        "description": "Second research paper"
      }
    ]
  },
  "api_key": "optional-anthropic-api-key"
}
```

### Required Fields
- `content` (string): User's question/message
- `context` (object): Project and document context
  - `project_id` (string): Project identifier
  - `project_name` (string): Project name
  - `documents` (array): Available documents with uuid, title, description

### Optional Fields
- `history` (array): Conversation history
- `context.project_description` (string): Additional project context
- `api_key` (string): Anthropic API key (uses env var if not provided)

## Output

```json
{
  "response": "Based on the documents, the key findings are...",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_read_input_tokens": 890
  },
  "citations": [
    {
      "type": "document",
      "document_index": 0,
      "start": 45,
      "end": 120,
      "text": "cited text from document"
    }
  ],
  "meta": {
    "tool_calls": [
      {
        "tool": "search_documents",
        "input": {
          "query": "key findings",
          "document_uuids": ["doc-uuid-1"]
        },
        "results_count": 5
      }
    ],
    "search_results": [
      {
        "text": "Chunk text...",
        "metadata": {
          "doc_title": "Paper 1",
          "document_uuid": "doc-uuid-1"
        },
        "score": 0.85
      }
    ]
  }
}
```

## Configuration

### config.yaml
```yaml
model: claude-sonnet-4-5-20250929
max_tokens: 16384  # Support long reports
temperature: 0
max_tool_calls: 10
search_top_k: 5
search_threshold: 0.7
```

### Environment Variables
- `ANTHROPIC_API_KEY`: Required for Claude API
- `OPENAI_API_KEY`: Required for embeddings
- `PINECONE_API_KEY`: Required for vector search

## Usage

```bash
bun py doc_agent_chat input.json
```

## Architecture

### Files
- `doc_agent_chat.py`: Main entry point with agentic loop
- `doc_search.py`: Database abstraction layer (Pinecone → PostgreSQL ready)
- `prompt.py`: System prompt builder
- `config.yaml`: Configuration

### Agentic Loop
1. Send user message to Claude with search tool available
2. If Claude calls the search tool:
   - Execute search in Pinecone
   - Return results to Claude
   - Continue conversation
3. Repeat up to 10 tool calls per turn
4. Return final response

### Search Tool
The agent has access to a `search_documents` tool:
- **query** (required): Search query text
- **document_uuids** (optional): Filter to specific documents

### Database Abstraction
The `DocSearch` class provides a DB-agnostic interface:
- Currently uses Pinecone
- Designed for easy switch to PostgreSQL
- Just reimplement `search()` method

## Security
- Frontend provides list of available document UUIDs
- Service validates tool calls against this list
- All searches filtered by project_id
- Prevents cross-project data access

## Notes
- Agent decides when to search (no upfront RAG decision)
- Tool results appended directly to conversation
- Supports writing long reports (16k max tokens)
- **Citations enabled**: Claude automatically cites sources when relevant
- Citations include document index, character positions, and cited text
- Simple prototype - no memory management or summarization yet
