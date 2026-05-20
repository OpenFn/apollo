---
id: global-chat.http-to-salesforce-three-steps-with-job-code
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

From-scratch three-step HTTP to transform to Salesforce workflow with job code for all three steps. The planner should call the workflow agent to produce a three-job workflow, then call the job code agent at least three times to fill in the bodies.

# quality_criteria

- Each job's body uses functions appropriate to its adaptor (HTTP get/post for the fetch step, JS for transform, Salesforce upsert for the destination).

# turn

## role

user

## content

Build a workflow that can fetch records from an HTTP endpoint, transform the data, and upsert contacts to Salesforce.
