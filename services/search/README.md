## Search (RAG)

The Search service allows for the retrieval of data relevant to user queries. Clients are 
encouraged to provide as much context as possible in their queries to receive the most pertinent information 
from the documents. 

This service primarily integrates Retrieval-Augmented Generation (RAG) with Apollo, enhancing the accuracy and 
relevance of the results returned to the user.

To make a search with curl:

```
curl -X POST https://apollo-staging.openfn.org/services/search --json @tmp/payload.json
```

With the CLI, returning to stdout:

```
openfn apollo search tmp/payload.json
```

To run direct from this repo (note that the server must be started):

```
bun py search tmp/payload.json -O
```

## Implementation

Currently, the service returns relevant data from a predefined corpus stored in a vector database.
The corpus is generated using the OpenAI Embedding Function and it embeds the OpenFn Documentaion into the database. 
This enables the retrieval of relevant context from the documents, thereby improving the results for other Apollo services.

## Payoad Reference

The input payload is a JSON object with the following structure

```json
{
    "api_key": "<OpenAI api key>",
    "query": "Tell me about OpenFn.",
}
```

## Response Reference

The server returns an array of relevant strings from the documents based on the provided query.
