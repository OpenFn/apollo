---
id: job-chat.duplicate-sections-additional
service: job_chat
---

# notes

Six identical POST calls. The user asks for retry-on-failure error handling on the THIRD one only. The service must use enough context to identify the right call, apply the change only there, and not accidentally drop any of the other five.

# quality_criteria

- Error handling is added only to the third POST call — the others remain unchanged.
- All six POST calls are still present in the suggested code (none accidentally removed).

# settings

## context.expression

```js
// Process and prepare data
fn(state => {
  const items = state.data.items.map(item => ({
    id: item.id,
    name: item.name,
    status: 'pending'
  }));

  return { ...state, items };
});

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);
```

## context.adaptor

@openfn/language-mailchimp@1.0.19

## suggest_code

true

# turn

## role

user

## content

I need to add error handling only to the third POST request to retry once if it fails.
