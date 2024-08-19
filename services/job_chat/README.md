## Job Chat

The Job Chat service enables a chat interface to uses writing an OpenFn job.

The service uses Anthropic Claude 3.5 Sonnet.

Clients must submit as much context about the job as they can (the current
expression, adaptor, input etc), along with the chat history, and a response
will be generated (along with a new history).

The Job Chat service is designed to be integrated with Lightning.

## Usage

Here is a minimal payload with a user question and no history:

```json
{
  "content": "how do I insert a new sobject record?",
  "context": {
    "expression": "// write your job code here",
    "adaptor": "@openfn/language-salesforce@4.6.10"
  }
}
```

To start a new chat with curl:

```
curl -X POST https://apollo-staging.openfn.org/services/job_chat --json @tmp/payload.json
```

With the CLI, returning to stdout:

```
openfn apollo job_chat tmp/payload.json -O
```

To run direct from this repo (note that the server must be started):

```
bun py job_chat tmp/payload.json
```

## Implementation

The service works by building a prompt with all the relevant context and sending
that along to the Anthropic API.

If an adaptor is provided, a complete listing of the adaptor's API is sent to
the model.

At the time of writing, a basic intro to OpenFn job writing is included in the
prompt. Later, we plan to use RAG processing to pull relevant information from
the OpenFn doc site.

The model is explicitly instructed to only answer questions about OpenFn and Job
Writing.

## Streaming

Right now the service will return the complete response when loaded.

Later, we may expose a streaming interface for better UX.

## Payoad Reference

The input payload is a JSON object with the following structure

```json
{
  "api_key": "<OpenAI api key>",
  "content": "The user's question",
  "history": [
    /* The complete chat history, as { role, content } objects */
  ],
  "context": {
    "expression": "The user's job code",
    "adaptor": "full specificer for the adaptor, eg @openfn/language-salesforce@4.10.0",
    "input": {
      /* The input state to the job */
    },
    "output": {
      /** The output from the last run */
    },
    "log": "the log from the last run"
  }
}
```

All context is optional, as is history.

## Response Reference

The server returns the following JSON response:

```json
{
  "response": "the model response as a string",
  "history": [
    /* Updated chat history */
  ]
}
```
