## Search Docsite (RAG)

This service searches the OpenFn Documentation vector database using a query and returns search matches. 

The documentation is vectorized through the `embed_docsite` service.

## Setup

Searching requires a populated `docsite` index. Every environment maintains its own, so there is no shared index to point at: run `embed_docsite` to create and fill yours before searching.

1. Create an account on [Pinecone](https://www.pinecone.io/) and set up a free cluster.
2. Add `PINECONE_API_KEY` and `OPENAI_API_KEY` to your `.env` file.

## Usage - Searching OpenFn Documentation

### With the CLI, returning to stdout:

```bash
openfn apollo search_docsite tmp/payload.json
```

### Directly from this repo:

```bash
bun py search_docsite --input tmp/payload.json
```

## Implementation
The service uses the DocsiteSearch class to query the database (Pinecone). It embeds semantic search queries using OpenAI. 

To compare backends on the same query, run the service twice with different
`backend` values and diff the results. This replaces the shadow-mode comparison
that was considered for the Postgres migration.

## Payload Reference
The input payload is a JSON object with the following structure:

```js
{
    "query": "What is Asana",         // Input query (required)
    "backend": "pinecone",            // 'pinecone' | 'postgres'. Defaults to DOCSITE_SEARCH_BACKEND, itself defaulting to pinecone.
    "docs_type": "adaptor_docs",      // Filter for adaptor_docs | adaptor_functions | general_docs (optional)
    "doc_title": "Asana",             // Filter for document title (optional)
    "top_k": 5,                       // Number of search results (optional)
    "threshold": 0.8,                 // Cosine cutoff. Only valid with strategy 'semantic'. (optional)
    "strategy": "semantic",           // Postgres backend only: 'semantic' | 'keyword' | 'hybrid'
    "batch_id": 12,                   // Postgres backend only: pin a specific batch (optional)
    "collection_name": "docsite-..."  // Pinecone backend only: pin a namespace (optional)
}
```

