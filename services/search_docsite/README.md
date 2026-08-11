## Search Docsite (RAG)

This service searches the OpenFn Documentation vector database using a query and returns search matches. 

The documenation is vectorized through the `embed_docsite` service.

## Usage - Searching OpenFn Documentation

The vector database used here is Pinecone. To obtain the env variables follow these steps:

1. Create an account on [Pinecone] and set up a free cluster.
2. Obtain the URL and token for the cluster and add them to the `.env` file.
3. You'll also need an OpenAI API key to generate embeddings for input queries.

### With the CLI, returning to stdout:

```bash
openfn apollo search_docsite tmp/payload.json
```
To run directly from this repo (note that the server must be started):

```bash
bun py search_docsite tmp/payload.json -O
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

