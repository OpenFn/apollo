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

