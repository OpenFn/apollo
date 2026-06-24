---
id: global-chat.multi-step.add-specific-step
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

From the workflow overview the user asks to add a new step with a clear,
concrete job: drop any record whose status isn't "active" before it reaches the
database write. Because the request is specific enough to write code against,
the planner should handle it — first calling the workflow agent to insert the
step and rewire the edges (fetch -> new filter step -> db write), then calling
the job code agent to fill the new step's body with the filtering logic. The
final YAML should contain a new step that actually filters on status, wired
between the fetch and write steps.

# quality_criteria

- A new step is inserted between fetch-records and write-records and the edges are rewired so data flows fetch -> new step -> write (the original fetch->write edge no longer skips the new step).
- The new step's body contains real filtering logic that keeps only records whose status is "active" (and discards the rest), rather than being left empty.
- The fetch-records body is preserved. (write-records may be adjusted only if it must consume a new state key the filter produces.)

# settings

## page

workflows/intake-to-postgres

## workflow_yaml

```yaml
name: intake-to-postgres
jobs:
  fetch-records:
    id: job-fetch-records-id
    name: Fetch Records
    adaptor: "@openfn/language-http@7.3.1"
    body: |
      get('https://intake.example.org/api/records', {
        query: { updated_since: $.lastRunAt }
      });
      fn(state => {
        const records = state.data?.records || [];
        return { ...state, records };
      });
  write-records:
    id: job-write-records-id
    name: Write Records to Postgres
    adaptor: "@openfn/language-postgresql@8.1.1"
    body: |
      each(
        $.records,
        insert('records', state => ({
          external_id: state.data.id,
          status: state.data.status,
          payload: JSON.stringify(state.data)
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "*/15 * * * *"
    enabled: true
edges:
  cron->fetch-records:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-records
    condition_type: always
    enabled: true
  fetch-records->write-records:
    id: edge-fetch-write
    source_job: fetch-records
    target_job: write-records
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-multi-step-add-specific-step-0005

# turn

## role

user

## content

We're getting a load of junk in the database. Can you add a step between fetching and the database write that throws away any record whose status isn't "active"?
