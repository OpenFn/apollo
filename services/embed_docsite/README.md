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

## Docs checkout

`general_docs` and `adaptor_docs` are read from a shallow `git clone` of
[OpenFn/docs](https://github.com/OpenFn/docs), kept at `services/embed_docsite/docsite_cache/` (gitignored). The first call in a process clones; every call after `fetch`es and `reset --hard`s onto the latest `main`.

The clone is blobless and sparse (`--filter=blob:none --sparse`, checked out to only `docs/` and `adaptors/`). If the refresh fails and a checkout already exists, the existing copy is served and a warning is logged — the run only fails if there is no checkout to fall back on. `git` must be on `PATH`.

`adaptor_functions` is a single JSON file from a different repo (`OpenFn/adaptors`), fetched over plain HTTP.

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
