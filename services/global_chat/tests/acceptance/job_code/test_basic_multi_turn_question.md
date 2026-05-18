---
id: global-chat.job-code.basic-multi-turn-question
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

Multi-turn conversation entirely about the same job code. The user has already asked two clarifying questions about the upsert step in a Salesforce contact sync and now asks a follow-up that requires keeping prior context in mind ("you mentioned external IDs — show me how to pick one"). The router should send this to job_code_agent. The response should pick up the thread from the prior assistant message rather than restarting the explanation, and should not propose unsolicited code edits.

# quality_criteria

- The response builds on the prior conversation about external IDs rather than restarting from scratch (e.g. does not re-introduce what an upsert is from the top).
- The response answers the user's question about choosing an external ID for the Contact object — preferring a stable, unique field like Email or an Salesforce-side External_Id__c field.
- The response does NOT rewrite the job body or propose a code change — the user is still asking conceptual questions.

# settings

## page

workflows/salesforce-contact-sync/upsert-contacts-to-salesforce

## workflow_yaml

```yaml
name: salesforce-contact-sync
jobs:
  fetch-contacts-from-hubspot:
    id: job-fetch-hubspot-id
    name: Fetch Contacts from HubSpot
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('https://api.hubapi.com/crm/v3/objects/contacts', {
        query: { limit: 100, properties: 'email,firstname,lastname,phone' }
      });
      fn(state => {
        const contacts = state.data.results || [];
        return { ...state, contacts };
      });
  upsert-contacts-to-salesforce:
    id: job-upsert-sf-id
    name: Upsert Contacts to Salesforce
    adaptor: "@openfn/language-salesforce@9.0.3"
    body: |
      each(
        $.contacts,
        upsert('Contact', 'Email', state => ({
          Email: state.data.properties.email,
          FirstName: state.data.properties.firstname,
          LastName: state.data.properties.lastname,
          Phone: state.data.properties.phone
        }))
      );
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: true
edges:
  webhook->fetch-contacts-from-hubspot:
    id: edge-wh-fetch
    source_trigger: webhook
    target_job: fetch-contacts-from-hubspot
    condition_type: always
    enabled: true
  fetch-contacts-from-hubspot->upsert-contacts-to-salesforce:
    id: edge-fetch-upsert
    source_job: fetch-contacts-from-hubspot
    target_job: upsert-contacts-to-salesforce
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-multi-turn-question-0002

# history

## turn

### role

user

### content

What is the second argument 'Email' doing in this upsert call?

## turn

### role

assistant

### content

In `upsert('Contact', 'Email', ...)` the second argument is the external ID field — the column Salesforce uses to decide whether a record already exists. If a Contact with that Email already exists in Salesforce, it gets updated; otherwise a new Contact is created. It's not the same as the Salesforce record Id.

## turn

### role

user

### content

So the external ID has to be unique across all contacts?

## turn

### role

assistant

### content

Yes — Salesforce requires the external ID field to be marked as External ID and Unique on the object. If duplicates exist, the upsert call will fail for those records. You generally want a field that's already enforced unique upstream (like Email, or a stable identifier from the source system).

# turn

## role

user

## content

OK that makes sense. If I wanted to use a Salesforce-side External_Id__c field on Contact instead of Email, what would I need to change about how I pick it? Don't rewrite the code yet — I just want to understand what makes a good external ID.
