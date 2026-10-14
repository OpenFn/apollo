---
id: workflow-guide
order: 50
---
<workflow guide>
A job is just one step in a workflow (or pipeline). Workflows are used
to automate processes and migrate data from system to system.

In OpenFn, each step works with a single backend system, or adaptor. Data is shared
between steps through the state object.

To build a successful workflow, we have to take the user's problem and break it down
step by step. Focus on one bit at a time. For example, when uploading from CommCare to Salesforce, we have to:
1. Download our data from CommCare in one step
2. Transform/map data into salesforce format in another step (with the common adaptor)
3. Upload the transformed data into salesforce in the final step
</workflow guide>
