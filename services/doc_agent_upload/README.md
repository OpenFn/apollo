# doc_agent_upload

Fetches plain text documents from URLs and indexes them to Pinecone for semantic search.

## Input

```json
{
  "doc_url": "https://example.com/document.txt",
  "user_description": "Description of document contents",
  "project_id": "project123"
}
```

## Output

```json
{
  "document_uuid": "uuid-generated-string",
  "doc_title": "document",
  "chunks_uploaded": 42,
  "status": "success"
}
```

## Usage

```bash
bun py doc_agent_upload input.json
```

## Notes

- Chunks documents using token-based splitting (512 tokens, 50 overlap)
- Uses OpenAI embeddings and Pinecone `doc-agent` index
- Namespaced by project_id for isolation
