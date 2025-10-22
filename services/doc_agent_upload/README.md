# doc_agent_upload

Upload and index documents for the document agent chat service.

## Overview

This service fetches plain text documents from URLs, chunks them using simple overlapped chunking, generates embeddings, and uploads them to Pinecone for semantic search.

## Input

```json
{
  "doc_url": "https://example.com/document.txt",
  "user_description": "A description of what this document contains",
  "project_id": "project123"
}
```

### Required Fields
- `doc_url` (string): URL to fetch the plain text document from
- `user_description` (string): User-provided description of the document
- `project_id` (string): Project identifier for document organization

## Output

```json
{
  "document_uuid": "uuid-generated-string",
  "doc_title": "document",
  "chunks_uploaded": 42,
  "status": "success"
}
```

## Configuration

### Environment Variables
- `OPENAI_API_KEY`: Required for generating embeddings
- `PINECONE_API_KEY`: Required for vector storage

### Chunking Parameters
- Chunk size: 512 tokens
- Chunk overlap: 50 tokens
- Uses token-based splitting with tiktoken (cl100k_base encoding)
- Ensures consistent embedding sizes and respects OpenAI token limits

### Pinecone Configuration
- Index name: `doc_agent`
- Namespace: `project-{project_id}`
- Embedding dimension: 1536 (OpenAI)
- Metric: cosine

## Usage

```bash
bun py doc_agent_upload input.json
```

## Architecture

### Files
- `doc_agent_upload.py`: Main entry point
- `doc_processor.py`: Document fetching and chunking
- `doc_indexer.py`: Pinecone upload logic

### Database Structure
Each chunk is stored with metadata:
- `project_id`: Project identifier
- `document_uuid`: Unique document identifier
- `doc_title`: Document title (extracted from URL)
- `user_description`: User-provided description
- `text`: The chunk content (embedded)

## Notes

- Only plain text documents are supported (no HTML parsing)
- Token-based chunking using tiktoken ensures consistent embedding sizes
- Suitable for any text type (documentation, articles, reports, etc.)
- Creates Pinecone index automatically if it doesn't exist
- One namespace per project for isolation
