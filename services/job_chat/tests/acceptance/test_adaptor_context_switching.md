---
id: job-chat.adaptor-context-switching
service: job_chat
---

# notes

User was on a Salesforce job page and asked "How do I get data?"; the assistant answered with SOQL. The user has now navigated to a DHIS2 job page and asks the same question again. The model should notice the page-prefix change and switch context to DHIS2-specific guidance.

# quality_criteria

- The response is specifically about fetching data from DHIS2 — not from Salesforce.
- The response references DHIS2 concepts (tracker, data values, events, programs, etc.) rather than SOQL or SQL.
- The response does not assume the previous Salesforce context still applies.

# settings

## context.expression

```js
fn(state => {
  return state;
});
```

## context.adaptor

@openfn/language-dhis2@8.0.7

## context.page_name

fetch-data

## suggest_code

false

# history

## turn

### role

user

### content

[pg:job_code/fetch-records/salesforce@9.0.3] How do I get data?

## turn

### role

assistant

### content

To get data from Salesforce, you can use the `query()` operation with SOQL (Salesforce Object Query Language). For example:

```js
query('SELECT Id, Name FROM Account WHERE Status = "Active"');
```

This will fetch records from Salesforce and store them in `state.data`.

# turn

## role

user

## content

How do I get data?
