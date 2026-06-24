---
id: global-chat.multi-step.change-current-step-using-other-steps
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The user is on the DHIS2 upload step (the last step) and asks to make it report
its record count "the way the other steps do". The earlier steps share a
convention: each ends with a console.log reporting how many records it handled.
To satisfy the request the assistant has to read at least one other step to see
what that convention looks like, then apply an equivalent count-log to the
current step only. This is a good fit for the planner: it should inspect another
step's body and then edit the upload step. A blind single-step route cannot know
what "the way the other steps do" means without reading them.

# quality_criteria

- The upload-to-dhis2 step is updated to log how many records/events it processed (a console.log reporting a count), consistent with the count-logging the other steps already do.
- The change is applied only to the upload-to-dhis2 body — fetch-submissions and clean-records are left unchanged.

# settings

## page

workflows/kobo-nutrition-to-dhis2/upload-to-dhis2

## workflow_yaml

```yaml
name: kobo-nutrition-to-dhis2
jobs:
  fetch-submissions:
    id: job-fetch-kobo-id
    name: Fetch Submissions from Kobo
    adaptor: "@openfn/language-kobotoolbox@4.3.1"
    body: |
      getSubmissions(state.configuration.formId, {
        query: { submittedAfter: $.lastRunAt }
      });
      fn(state => {
        const submissions = state.data?.results || [];
        console.log(`Fetched ${submissions.length} submissions from Kobo`);
        return { ...state, submissions };
      });
  clean-records:
    id: job-clean-id
    name: Clean Records
    adaptor: "@openfn/language-common@3.3.3"
    body: |
      fn(state => {
        const records = state.submissions
          .filter(s => s.child_name && s.muac && s.org_unit)
          .map(s => ({
            name: s.child_name,
            muac: Number(s.muac),
            orgUnit: s.org_unit
          }));
        console.log(`Cleaned ${records.length} records, dropped ${state.submissions.length - records.length}`);
        return { ...state, records };
      });
  upload-to-dhis2:
    id: job-upload-dhis2-id
    name: Upload to DHIS2
    adaptor: "@openfn/language-dhis2@8.1.1"
    body: |
      each(
        $.records,
        create('events', state => ({
          program: state.configuration.programId,
          orgUnit: state.data.orgUnit,
          occurredAt: new Date().toISOString(),
          dataValues: [
            { dataElement: state.configuration.muacDataElement, value: state.data.muac }
          ]
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 6 * * *"
    enabled: true
edges:
  cron->fetch-submissions:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-submissions
    condition_type: always
    enabled: true
  fetch-submissions->clean-records:
    id: edge-fetch-clean
    source_job: fetch-submissions
    target_job: clean-records
    condition_type: on_job_success
    enabled: true
  clean-records->upload-to-dhis2:
    id: edge-clean-upload
    source_job: clean-records
    target_job: upload-to-dhis2
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-multi-step-current-using-others-0001

# history

## turn

### role

user

### content

[pg:workflows/kobo-nutrition-to-dhis2] This pulls nutrition submissions from Kobo, tidies them up and pushes them into DHIS2 as events.

## turn

### role

assistant

### content

That's right — the workflow fetches submissions from Kobo each morning, cleans them into MUAC records, and creates DHIS2 events for each one.

# turn

## role

user

## content

When I read the logs I can see how many records the earlier steps handled, but this one says nothing. Can you make it report its count the way the others do?
