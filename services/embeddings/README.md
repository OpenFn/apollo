# Embeddings

This service manages vector embeddings and similarity searches.

It is primarily used by other services. For an example, see the embeddings_demo service.

This service provides a VectorStore class which can be imported to initialise and search an embedding collection. 

## Implementation Notes

This service relies on LangChain to allow for different embedding storage providers and different types of embeddings.

## Usage

This service is currently not designed to be used directly from this repo.

The VectorStore class that this service provides can be imported, instantiated and searched by another service like this:

```py
from embeddings.embeddings import VectorStore

store = VectorStore(
    collection_name="demo_project",
    vectorstore_type="zilliz",
    embedding_type="openai",
    connection_args = {
        "uri": os.getenv('ZILLIZ_CLOUD_URI'),
        "token": os.getenv('ZILLIZ_CLOUD_API_KEY')
    }
)

results = store.search("my input query", search_kwargs={"k": 1})
```

For more details, see the embeddings_demo service.