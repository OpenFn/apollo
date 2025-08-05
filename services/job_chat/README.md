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
  "content": "how do I insert a new subject record?",
  "context": {
    "expression": "// write your job code here",
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
  "content": "how do I insert a new subject record?",
  "history": [
    {"role": "user", "content": "How do I use Salesforce?"},
    {"role": "assistant", "content": "Salesforce provides many operations..."}
  ],
  "context": {
    "expression": "// write your job code here",
    "adaptor": "@openfn/language-salesforce@4.6.10",
    "input": {"data": {"field1": "value1"}},
    "output": {"previous": "output"},
    "log": "execution log text"
  },
  "meta": {
    "rag": {
      "search_results": []
    }
  },
  "api_key": "<Anthropic API key>"
}
```

All context is optional, as is history.

## Response Reference

The server returns the following JSON response:

```json
{
  "response": "To insert a new subject record in Salesforce, you can use the create operation...",
  "suggested_code": "create('Account', {\n  Name: 'Test Account',\n  Industry: 'Technology'\n});",
  "history": [
    {"role": "user", "content": "How do I use Salesforce?"},
    {"role": "assistant", "content": "Salesforce provides many operations..."},
    {"role": "user", "content": "how do I insert a new sobject record?"},
    {"role": "assistant", "content": "To insert a new sobject record in Salesforce, you can use the create operation..."}
  ],
  "usage": {
    "input_tokens": 526,
    "output_tokens": 164,
    "cache_creation_input_tokens": 12525,
    "cache_read_input_tokens": 0
  },
  "meta": {
    "rag": {
      "search_results": [],
      "search_results_sections": [],
      "search_queries": []
    }
  }
}
```

## Backwards Compatibility

For backwards compatibility, the service supports an optional `use_new_prompt` flag. This allows existing integrations to maintain their current behavior while new integrations can use the improved prompt format.

```json
{
  "content": "how do I insert a new subject record?", 
  "context": { 
    "expression": "// write your job code here", 
  }, 
  "use_new_prompt": false 
}
```

When `use_new_prompt` is `false` (or omitted), the service uses the original prompt format where:
- Code suggestions are embedded directly within the `response` text as markdown code blocks
- The `suggested_code` field will not be included in the response
- The `application_status` field will not be included in the response

When `use_new_prompt` is `true`, the service uses the new structured format where:
- Edited job code is separated into a dedicated `suggested_code` field
- The `response` field contains explanatory text and code blocks (e.g. example code that might not relate to the current job code)
- When code edits are applied, an additional `application_status` field may be included with details about the code edit application

This maintains compatibility with existing integrations that expect code to be embedded in the response text rather than in a separate field, as the service originally functioned.