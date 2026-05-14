---
id: job-chat.contextualised-input
service: job_chat
judges: [general, openfn_code_quality]
---

# notes

All payload fields populated: history, job code, multiple adaptors, ids, and pre-injected RAG search results in meta. The service should pick up on the RAG hints (HTTP adaptor error handling, retry logic) and produce a suggested_code that differs from the original.

# quality_criteria

- The suggested_code is meaningfully modified from the original to add error handling and retry logic, drawing on the pre-injected RAG search results rather than ignoring them.

# settings

## context.expression

```js
// Get data from external API
get('https://api.example.com/data');

// Process and transform data
fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));

  return { ...state, transformed };
});

// Send transformed data to destination
post('https://destination.org/upload', state => state.transformed);
```

## context.adaptor

@openfn/language-fhir-4@0.1.10

## context.adaptors

```json
["@openfn/language-http", "@openfn/language-common"]
```

## context.projectId

project-xyz789

## context.jobId

job-abc123

## meta.rag

```json
{
  "search_queries": [
    "http adaptor error handling",
    "openfn retry logic"
  ],
  "search_results": [
    {
      "title": "HTTP Adaptor Error Handling",
      "url": "https://docs.openfn.org/adaptors/http#error-handling",
      "content": "The HTTP adaptor provides mechanisms for handling connection errors and retrying failed requests. Use the maxRetries option to specify retry attempts."
    },
    {
      "title": "Common Adaptor Documentation",
      "url": "https://docs.openfn.org/adaptors/common#error-handling",
      "content": "Error handling can be implemented using standard JavaScript try/catch blocks or with the withError helper function."
    }
  ]
}
```

## suggest_code

true

# history

## turn

### role

user

### content

I need to add error handling to my API integration job. What's the best approach?

## turn

### role

assistant

### content

There are several approaches to handling errors in API calls. You can use try/catch blocks, implement retry logic, or use built-in error handling functions. Could you share your current job code so I can provide specific recommendations?

# turn

## role

user

## content

Can you add error handling to this job that will log the error message and retry the operation once if the API call fails?
