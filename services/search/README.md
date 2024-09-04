## Search (RAG)

The Search service allows for the retrieval of data relevant to user queries. Clients are encouraged to provide as much context as possible in their queries to receive the most pertinent information from the documents.

This service primarily integrates Retrieval-Augmented Generation (RAG) with Apollo, enhancing the accuracy and relevance of the results returned to the user.

## Usage - Search Service

### To make a search with `curl`:

```bash
curl -X POST https://apollo-staging.openfn.org/services/search --json @tmp/payload.json
```

### With the CLI, returning to stdout:

```bash
openfn apollo search tmp/payload.json
```
To run directly from this repo (note that the server must be started):

```bash
bun py search tmp/payload.json -O
```


## Usage - Embedding OpenFn Docs
This service also includes the embedding of OpenFn docs to a vector database. The vector database used here is Zilliz. To obtain the env variables follow these steps:

1. Create an account on [Zilliz](https://zilliz.com/) and set up a free cluster.
2. Obtain the URL and token for the cluster and add them to the `.env` file.
3. You'll also need an OpenAI API key to generate embeddings.

There are two ways to run the embed the docs:

### Running the Generate Embeddings File
Use the poetry command to run the service. You will need to clone the docs repo in this case using:

```bash
git clone --depth 1 https://github.com/OpenFn/docs.git tmp
```

Then run:
```bash
poetry run python services/search/generate_docs_embeddings.py tmp/docs openfn_docs
```
Here, tmp/docs is the path to the OpenFn docs and openfn_docs is the name of the collection in the vector database.

### Docker
Alternatively, run the Docker file directly using:

```bash
docker build --secret id=_env,src=.env -t apollo .
```

## Implementation
Currently, the service returns relevant data from the job docs stored in a vector database. The corpus is generated using the OpenAI Embedding Function and embeds the OpenFn Documentation into the database. This enables the retrieval of relevant context from the documents, thereby improving the results for other Apollo services. You also have an option to summarize the docs based on your query or increase the number of chunks retrieved from the database.

## Payload Reference
The input payload is a JSON object with the following structure:

```json
{
    "api_key": "<OpenAI api key>",
    "query": "What are jobs in OpenFn?",
    "limit": 10, // A custom limit for number of chunks retrieved ranging from 1 to 15
    "collection_name": "openfn_docs", // Might be helpful when we embed the adaptor docs to a new collection
    "summarize": true // Summarizes context based on your query
}
```

## Response Reference
The server returns an array of relevant strings from the documents based on the provided query.