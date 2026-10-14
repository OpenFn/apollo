---
id: edge-creation
order: 50
---

## Rules for Edge Creation

1. The first job should always connect to the trigger, and the trigger can only connect to ONE job. If the user wants multiple things to happen in parallel in the first step, you should pick one of them to happen first.
2. Each subsequent job should connect to the previous job with one condition_type: on_job_success, on_job_failure, always or js_expression (for the latter, also add a condition_expression in quotes e.g. '!state.error')
3. For branching workflows, create conditional edges as appropriate
4. Edges should be enabled by default
5. Edges execute simultaneously and independently. When multiple edges target the same job (e.g., job-3 receives edges from both job-1 and job-2), that target job will run once per incoming edge. If job-1 and job-2 both succeed, job-3 executes twice—once triggered by each edge. This is not a merge or wait operation; each edge fires its target independently when its condition is met.
