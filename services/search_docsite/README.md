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

## Payload Reference
The input payload is a JSON object with the following structure:

```js
{
    "query": "What is Asana", // Input query
    "collection_name": "Docsite-20250225", // Name of the collection in the vector database
    "docs_type": "adaptor_docs", // Filter for document type adaptor_docs, adaptor_functions, general_docs (optional)
    "doc_title": "Asana", // Filter for document title (optional)
    "top_k": 5 // Adjust the number of search results (optional)
}
```

