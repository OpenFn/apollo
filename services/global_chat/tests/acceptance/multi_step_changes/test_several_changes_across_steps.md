---
id: global-chat.multi-step.several-changes-across-steps
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

From the workflow overview the user asks for two unrelated code changes that
land on two different steps in one message: the fetch step should also bring
back phone numbers, and the final Salesforce upsert should skip contacts with no
email. This needs the planner, which should call the job code agent at least
twice (once per affected step). Each change must land on the right step and the
untouched transform step must be preserved.

# quality_criteria

- Phone numbers are picked up at the fetch step and carried through so they reach Salesforce (it is fine, and expected, for transform-contacts to also be updated to map the phone field through).
- Contacts without an email address are skipped rather than upserted to Salesforce (the skip may be implemented at the transform or the upsert step).
- Both requested changes are made; neither is silently dropped.

# settings

## page

workflows/crm-to-salesforce-sync

## workflow_yaml

```yaml
name: crm-to-salesforce-sync
jobs:
  fetch-contacts:
    id: job-fetch-contacts-id
    name: Fetch Contacts from CRM
    adaptor: "@openfn/language-http@7.3.1"
    body: |
      get('https://crm.example.org/api/contacts', {
        query: { fields: 'id,first_name,last_name,email', updated_since: $.lastRunAt }
      });
      fn(state => {
        const contacts = state.data?.contacts || [];
        return { ...state, contacts };
      });
  transform-contacts:
    id: job-transform-id
    name: Transform Contacts
    adaptor: "@openfn/language-common@3.3.3"
    body: |
      fn(state => {
        const records = state.contacts.map(c => ({
          ExternalId__c: c.id,
          FirstName: c.first_name,
          LastName: c.last_name,
          Email: c.email
        }));
        return { ...state, records };
      });
  upsert-to-salesforce:
    id: job-upsert-sf-id
    name: Upsert Contacts to Salesforce
    adaptor: "@openfn/language-salesforce@9.1.1"
    body: |
      each(
        $.records,
        upsert('Contact', 'ExternalId__c', state => state.data)
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "30 2 * * *"
    enabled: true
edges:
  cron->fetch-contacts:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-contacts
    condition_type: always
    enabled: true
  fetch-contacts->transform-contacts:
    id: edge-fetch-transform
    source_job: fetch-contacts
    target_job: transform-contacts
    condition_type: on_job_success
    enabled: true
  transform-contacts->upsert-to-salesforce:
    id: edge-transform-upsert
    source_job: transform-contacts
    target_job: upsert-to-salesforce
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-multi-step-several-changes-0003

# turn

## role

user

## content

Couple of things I want to fix here: the contacts we pull in should include their phone numbers too, and at the end please don't push anyone across to Salesforce if they don't have an email on file.
