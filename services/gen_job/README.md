## Job Generation Service

The Job Generation service allows for the generation of job expresssions relevant to user queries. Job expressions are
a important part of the OpenFn workflows. This service allows user to generate them based on simple text instructions along
with the adaptor information and the current state.

To make a search with curl:

```
curl -X POST https://apollo-staging.openfn.org/services/gen_job --json @tmp/payload.json
```

With the CLI, returning to stdout:

```
openfn apollo gen_job tmp/payload.json
```

To run direct from this repo (note that the server must be started):

```
bun py gen_job tmp/payload.json -O
```

## Implementation

The service takes in the text instructions, current state, existing expression and the adaptor information, 
and generates a job expression for the user. The service uses other existing services like the search service to 
retrieve relevant data from the OpenFn docs and the adaptor description service for adding the adaptor information.
All of this context is given to the Model and it generates the job expression based on the text instructions.

## Payoad Reference

The input payload is a JSON object with the following structure

```json
{
    "api_key": "<OpenAI api key>",
    "existing_expression": "Your existing job expression",
    "adaptor": "@openfn/language-dhis2@4.0.3",
    "state": "Current state",
    "instruction": "A simple text instruction.",
    "use_embeddings": true // set to false if you don't want to use RAG service
}
```

## Response Reference

The server returns a job expression based on the provided query.

## RAG service setup
In order to use the RAG service we need to configure the vector database first. Create an account on [Zilliz](https://zilliz.com/) and create a free cluster. Obtain the URL and token to the cluster and add them to the env file. We will also need a OpenAI API key to create the embeddings. Then we run the docker command or the simply run the generate embeddings file. 

Docker: 
```
docker build --secret id=_env,src=.env -t apollo .
```
With the docker command we do not need to setup the docs repository.

Running the file:
```
poetry run python services/search/generate_docs_embeddings.py tmp/docs collection_name
```
Here we will need to clone the git repo using `git clone --depth 1 https://github.com/OpenFn/docs.git /tmp` and then run the above command. 

For now we are just embedding the job writing docs into the vector database.

## Job processor for multiple inputs

This file helps you run multiple inputs with a single instruction (the server must be started with bun dev). The instrtuction to run this file is 
```
poetry run python services/gen_job/job_processor.py -i tmp/input.json -o tmp/output.md
```
Here the input file contains a array of inputs in this format:
```json
[
  {
    "api_key": "your_api_key",
    "existing_expression": "",
    "adaptor": "Adaptor-1",
    "state": {},
    "instruction": "Instruction for expample 1",
    "use_embeddings":true
  },
  {
    "api_key": "your_api_key",
    "existing_expression": "",
    "adaptor": "Adaptor-2",
    "state": {},
    "instruction": "Instruction for expample 2",
    "use_embeddings": false
  }
]
```
A sample input file has been added to results/input.json

You will need to add the zilliz database url and token to the env file in order to use the RAG serice. You can also skip the use of RAG by setting 'use_embeddings' option as false. 
