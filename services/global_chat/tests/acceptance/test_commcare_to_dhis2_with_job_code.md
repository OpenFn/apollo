---
id: global-chat.commcare-to-dhis2-with-job-code
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

From-scratch CommCare to DHIS2 workflow with job code for both steps. No existing YAML, no history. The planner should be invoked, call the workflow agent to produce a two-job workflow, then call the job code agent at least twice to fill in the bodies.

# quality_criteria

- The response explains the workflow's purpose in plain language a non-engineer can follow.
- The job code for the CommCare step calls CommCare adaptor functions (e.g. submissions, forms, cases), not generic JavaScript.
- The job code for the DHIS2 step calls DHIS2 adaptor functions (e.g. create, upsert, trackedEntities), not generic JavaScript.

# turn

## role

user

## content

Create a workflow that fetches patient cases from CommCare and registers them in DHIS2.
