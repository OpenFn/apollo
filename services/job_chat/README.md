## Job Chat

The Job Chat service enables a chat interface to uses writing an OpenFn job.

The service uses Anthropic's Claude API.

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
    "expression": "// write your job code here"
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

## Payload Reference

The input payload is a JSON object with the following structure

```json
{
  "content": "how do I insert a new sobject record?",
  "history": [
    { "role": "user", "content": "How do I use Salesforce?" },
    { "role": "assistant", "content": "Salesforce provides many operations..." }
  ],
  "context": {
    "expression": "// write your job code here",
    "adaptor": "@openfn/language-salesforce@4.6.10",
    "page_name": "my_job",
    "input": { "data": { "field1": "value1" } },
    "output": { "previous": "output" },
    "log": "execution log text"
  },
  "meta": {
    "rag": {
      "search_results": []
    }
  },
  "suggest_code": true,
  "stream": false,
  "download_adaptor_docs": true,
  "refresh_rag": false,
  "api_key": "<Anthropic API key>"
}
```

All context is optional, as is history.

The `download_adaptor_docs` flag (defaults to `true`) controls whether adaptor docs are automatically loaded before building prompts. Set to `false` to skip auto-loading.

## Response Reference

The server returns the following JSON response:

```json
{
  "response": "To insert a new sobject record in Salesforce, you can use the create operation...",
  "history": [
    { "role": "user", "content": "[pg:job_code/my_job/salesforce@4.6.10] How do I use Salesforce?" },
    {
      "role": "assistant",
      "content": "Salesforce provides many operations..."
    },
    { "role": "user", "content": "[pg:job_code/my_job/salesforce@4.6.10] how do I insert a new sobject record?" },
    {
      "role": "assistant",
      "content": "To insert a new sobject record in Salesforce, you can use the create operation..."
    }
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
      "search_queries": [],
      "usage": {}
    }
  }
}
```

## Code Suggestions

Instead of having the model reply with in-line code snippets, the service can
return an entire new job expression in the response. This is expected to drive a
much better user experience with the assistant.

This uses a patching system internally to apply code suggestions form the model
into the user's expression.

The response includes a `suggested_code` key, as well as a `diff` key which
provides diagnostic information about the patch.

```json
{
  "response": "To insert a new sobject record in Salesforce, you can use the create operation...",
  "suggested_code": "create('Account', {\n  Name: 'Test Account',\n  Industry: 'Technology'\n});",
  "diff": {
    "patches_applied": 1,
    "warning": "failed to apply edit"
  },
  "history": [...],
  "usage": { ... },
  "meta": {... }
}
```

To use this approach, set `suggest_code: true` in the request payload:

```json
{
  "content": "how do I insert a new sobject record?",
  "context": {
    "expression": "// write your job code here"
  },
  "suggest_code": true
}
```

For backwards compatibility, this functionality is disabled by default.

**When `suggest_code` is `false` (or omitted):**
- Code suggestions are embedded directly within the `response` text as markdown code blocks
- The `suggested_code` and `diff` fields will not be included in the response

**When `suggest_code` is `true`:**
- Edited job code is returned in a dedicated `suggested_code` field
- The `response` field contains explanatory text
- A `diff` field provides details about code edit application with `patches_applied` count and optional `warning` messages
