## Embed Docsite (RAG)

This service embeds the OpenFn Documentation to a vector database. It downloads, chunks, processes metadata, embeds and uploads the documentation to a vector database (Pinecone). 

## Usage - Embedding OpenFn Documentation

The vector database used here is Pinecone. To obtain the env variables follow these steps:

1. Create an account on [Pinecone] and set up a free cluster.
2. Obtain the URL and token for the cluster and add them to the `.env` file.
3. You'll also need an OpenAI API key to generate embeddings.

### With the CLI, returning to stdout:

```bash
openfn apollo embed_docsite tmp/payload.json
```
To run directly from this repo (note that the server must be started):

```bash
bun py embed_docsite tmp/payload.json -O
```

## Implementation
The service uses the DocsiteProcessor to download the documentation and chunk it into smaller parts. The DocsiteIndexer formats metadata, creates a new collection, embeds the chunked texts (OpenAI) and uploads them into the vector database (Pinecone).

The chunked texts can be viewed in `tmp/split_sections`.

## Payload Reference
The input payload is a JSON object with the following structure:

```js
{
    "docs_to_upload": ["adaptor_docs", "general_docs", "adaptor_functions"], // Select 1-3 types of documentation to upload
    "collection_name": "Docsite-20250225", // Name of the collection in the vector database.
}
```

