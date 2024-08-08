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
    "instruction": "A simple text instruction."
}
```

## Response Reference

The server returns a job expression based on the provided query.
