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

The write target is independent of the read backend (`DOCSITE_SEARCH_BACKEND`),
so a Postgres batch can be built while Pinecone still serves search traffic.

The input payload is a JSON object. All parameters are optional:

```js
{
    "target": "pinecone",             // 'pinecone' | 'postgres'. Defaults to pinecone. Chooses the write destination.
    "docs_to_upload": ["adaptor_docs", "general_docs", "adaptor_functions"],
    "docs_to_ignore": ["job-examples.md", "release-notes.md"],
    "chunk_target_length": 1000,      // Target chunk size in characters
    "chunk_min_length": 700,          // Minimum chunk size before merging with the next split

    // Pinecone target only:
    "collection_name": "docsite-20250225",  // Namespace (defaults to the current timestamp)
    "index_name": "docsite",
    "max_total_collections": 3,

    // Postgres target only:
    "keep_batches": 2                 // Number of recent complete batches to retain when pruning
}
```
