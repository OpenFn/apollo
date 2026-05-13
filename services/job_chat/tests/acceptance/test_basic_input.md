---
id: job-chat.basic-input
service: job_chat
---

# notes

Basic input: a simple job-code modification request. The service returns a response with both a text answer and a suggested_code patch when suggest_code is true.

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

@openfn/language-gmail@2.0.2

## suggest_code

true

# turn

## role

user

## content

Can you add error handling to this job that will log the error message and retry the operation once if the API call fails?
