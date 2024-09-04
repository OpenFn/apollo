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

## RAG Service Setup

To use the RAG service, the first step is to configure the vector database. Follow these instructions:

1. Create an account on [Zilliz](https://zilliz.com/) and set up a free cluster.
2. Obtain the URL and token for the cluster and add them to the `.env` file.
3. You'll also need an OpenAI API key to generate embeddings.

### Docker:

To build the Docker image and run the service, use the following command:

```bash
docker build --secret id=_env,src=.env -t apollo .
```
When using Docker, you don't need to set up the docs repository separately.

### Running the File:
If you prefer to run the service without Docker, clone the GitHub repository and run the following command:

```bash 
git clone --depth 1 https://github.com/OpenFn/docs.git /tmp
poetry run python services/search/generate_docs_embeddings.py tmp/docs collection_name
```
This will embed the job writing docs into the vector database.

## Job Processor for Multiple Inputs
This script allows you to process multiple inputs with a single file. Ensure the server is running with `bun dev` before executing the command below:

```bash
poetry run python services/gen_job/job_processor.py -i tmp/input.json -o tmp/output.md
```

### Input File Format:
The input file should contain an array of inputs in the following format:

```json
[
  {
    "api_key": "your_api_key",
    "existing_expression": "",
    "adaptor": "Adaptor-1",
    "state": {},
    "instruction": "Instruction for example 1",
    "use_embeddings": true
  },
  {
    "api_key": "your_api_key",
    "existing_expression": "",
    "adaptor": "Adaptor-2",
    "state": {},
    "instruction": "Instruction for example 2",
    "use_embeddings": false
  }
]
```
A sample input file is provided at results/input.json.

### Additional Notes:
Make sure to add the Zilliz database URL and token to the .env file to use the RAG service.
If you wish to skip using RAG, set the use_embeddings option to false in the input file.
vbnet
