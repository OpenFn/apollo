---
id: global-chat.multi-step.change-different-step-from-another-step
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The user is parked on the send-summary step (the last step) but the change they
ask for is about the first step — they want the CommCare fetch to only pull
cases changed recently instead of everything. This is still a single-step edit,
just not the focused one, so the router should resolve the target to the
fetch-cases step (job_key = fetch-cases) and route directly to job_code_agent.
The model must not edit the step the page points at; it must edit the step the
request is actually about.

# quality_criteria

- The fetch-cases step is changed so it no longer pulls every case each run — e.g. a date/modified filter on the query (roughly the last week) OR incremental sync (a cursor / since-last-run filter). Either approach satisfies the intent.
- The change lands on the fetch step's logic. The send-summary step (the page the user is currently on) is NOT modified just because it is the focused step.

# settings

## page

workflows/commcare-case-sync/send-summary

## workflow_yaml

```yaml
name: commcare-case-sync
jobs:
  fetch-cases:
    id: job-fetch-cases-id
    name: Fetch Cases from CommCare
    adaptor: "@openfn/language-commcare@4.1.1"
    body: |
      get('/api/v0.5/case', {
        query: { type: 'patient', limit: 100 }
      });
      fn(state => {
        const cases = state.data?.objects || [];
        return { ...state, cases };
      });
  write-to-db:
    id: job-write-db-id
    name: Write Cases to Postgres
    adaptor: "@openfn/language-postgresql@8.1.1"
    body: |
      each(
        $.cases,
        upsert('patients', 'case_id', state => ({
          case_id: state.data.case_id,
          full_name: state.data.properties?.full_name,
          dob: state.data.properties?.dob,
          updated_at: state.data.server_date_modified
        }))
      );
  send-summary:
    id: job-send-summary-id
    name: Send Run Summary
    adaptor: "@openfn/language-http@7.3.1"
    body: |
      post('https://hooks.example.org/notify', state => ({
        body: {
          workflow: 'commcare-case-sync',
          synced: state.cases.length,
          finishedAt: new Date().toISOString()
        }
      }));
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 */4 * * *"
    enabled: true
edges:
  cron->fetch-cases:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-cases
    condition_type: always
    enabled: true
  fetch-cases->write-to-db:
    id: edge-fetch-write
    source_job: fetch-cases
    target_job: write-to-db
    condition_type: on_job_success
    enabled: true
  write-to-db->send-summary:
    id: edge-write-summary
    source_job: write-to-db
    target_job: send-summary
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-multi-step-change-different-step-0002

# turn

## role

user

## content

This runs every four hours but it's grabbing every case each time, which is wasteful. The first step should only pull cases that have changed in the last week or so.
