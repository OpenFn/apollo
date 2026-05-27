---
id: global-chat.job-code.basic-first-turn-question
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

First conversation turn on a job step page. The user asks a non-modifying question about the existing job code on the page they are viewing. The router should send this to the job_code_agent (the focused step is unambiguous from the page URL). The response should explain the code in plain language without attempting to rewrite or "improve" it. No workflow_yaml diff and no job_code attachment with edits is expected.

# quality_criteria

- The response explains the existing job code in plain language and references concepts that actually appear in the code on the page (cursor, getSubmissions, fn).
- The response does NOT propose a code change or generate replacement code — the user only asked a question.
- The response stays focused on the kobo-fetch-submissions step, not the postgres-insert step that follows it.

# settings

## page

workflows/kobo-attendance-sync/kobo-fetch-submissions

## workflow_yaml

```yaml
name: kobo-attendance-sync
jobs:
  kobo-fetch-submissions:
    id: job-kobo-fetch-id
    name: Fetch Kobo Submissions
    adaptor: "@openfn/language-kobotoolbox@4.2.3"
    body: |
      cursor($.lastRunAt, { defaultValue: 'today' });
      getSubmissions(
        { formId: 'aXYZ123attendance' },
        { startDate: $.cursor }
      );
      fn(state => {
        const submissions = state.data.results || [];
        console.log(`Fetched ${submissions.length} submissions`);
        return { ...state, submissions };
      });
  postgres-insert-attendance:
    id: job-postgres-insert-id
    name: Insert Attendance Rows
    adaptor: "@openfn/language-postgresql@6.5.1"
    body: |
      each(
        $.submissions,
        insert('attendance', state => ({
          submission_id: state.data._id,
          learner_id: state.data.learner_id,
          present: state.data.present === 'yes',
          recorded_at: state.data._submission_time
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 6 * * *"
    enabled: true
edges:
  cron->kobo-fetch-submissions:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: kobo-fetch-submissions
    condition_type: always
    enabled: true
  kobo-fetch-submissions->postgres-insert-attendance:
    id: edge-fetch-insert
    source_job: kobo-fetch-submissions
    target_job: postgres-insert-attendance
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-basic-first-turn-0001

# turn

## role

user

## content

What does the cursor() call at the top of this job actually do? I didn't write it and I'm not sure why it's there.
