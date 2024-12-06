# Embeddings

This is a demo service to provide an example for leveraging the embeddings service.

This demo uses demo data to create an embedding collection and searches it with an input query text.

## Implementation Notes

This demo currently uses the Zilliz embedding storage provider for OpenAI embeddings, and requires both Zilliz (URI, Token) and OpenAI credentials to run.

## Usage

This demo can be run from the services folder via the entry.py module:

```bash
python entry.py embeddings_demo embeddings_demo/demo_data/input_data.json tmp/output.json
```
