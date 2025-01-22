# Embed LOINC Dataset

This a service which preprocesses a LOINC dataset and uploads it to an embedding storage provider for searching. As using this service will re-upload the dataset to the embedding storage (which may incur costs), it should only be used if the dataset in the embedding storage needs to be altered.

If you only need to search the LOINC dataset, you can directly connect to the existing embedding store through the `loinc_store` module in the embeddings service (see the function `connect_loinc`).

## Implementation Notes

This service uses the Pinecone embedding storage provider for OpenAI embeddings, and requires both Pinecone and OpenAI credentials to run.

## Usage

This service can be run from the services folder via the entry.py module. The input is a single text to test the uploaded embeddings:

```bash
python entry.py embed_loinc_dataset tmp/vectorstore_search_input_example.json tmp/output_vectorstore.json
```
