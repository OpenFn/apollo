---
id: global-chat.gsheets-transform-salesforce-with-cron
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Semi-specific request: cron trigger at midnight, fetch from Google Sheets, transform, upsert to Salesforce. The Salesforce upsert step requires field mapping decisions the user hasn't provided. The planner should acknowledge the missing details rather than inventing field mappings silently.

# quality_criteria

- The response acknowledges that the Salesforce upsert needs field-mapping details from the user (object type, key fields, source-to-target mapping).
- If the response generates job code or YAML, it does not silently fabricate field mappings the user did not provide.

# turn

## role

user

## content

Can you make a workflow that triggers at midnight, fetches data from Google Sheets, transforms it, and upserts it into Salesforce?
