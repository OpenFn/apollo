## Embed Docsite (RAG)

This service embeds the OpenFn Documentation to a vector database. It downloads, chunks, processes metadata, embeds and uploads the documentation to a vector database (Pinecone). 

## Setup

Every environment maintains its own vector store, so there is no shared index to point at. Run this service to populate your own before using `search_docsite`.

1. Create an account on [Pinecone](https://www.pinecone.io/) and set up a free cluster.
2. Add `PINECONE_API_KEY` and `OPENAI_API_KEY` to your `.env` file.

The service creates the `docsite` index if it does not already exist.

## Usage - Embedding OpenFn Documentation

### With the CLI, returning to stdout:

```bash
openfn apollo embed_docsite tmp/payload.json
```

### Directly from this repo:

```bash
bun py embed_docsite
```

The payload is optional. With no `--input`, the service indexes all documentation using the defaults below; to customise it, pass a payload file:

```bash
bun py embed_docsite --input tmp/payload.json
```

A full run downloads the entire docs site and embeds several thousand chunks, so allow upwards of ten minutes.

## Implementation
The service uses the DocsiteProcessor to download the documentation and chunk it into smaller parts. The DocsiteIndexer formats metadata, creates a new collection, embeds the chunked texts (OpenAI) and uploads them into the vector database (Pinecone).

The chunked texts can be viewed in `tmp/split_sections`.

## Payload Reference
The input payload is a JSON object. All parameters are optional:

```js
{
    "docs_to_upload": ["adaptor_docs", "general_docs", "adaptor_functions"], // Select from 3 types of documentation to upload
    "collection_name": "docsite-20250225", // Name of the collection in the vector database (defaults to the current date)
    "index_name": "docsite", // Name of the index in the vector database (an index contains collections; defaults to docsite)
    "docs_to_ignore": ["job-examples.md", "release-notes.md"], // Titles of documents that should not be indexed
    "max_total_collections" : 3 // The max number of collections to keep in the vector database. This will delete older collections by date.
}
```
