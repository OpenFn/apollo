---
id: global-chat.multi-step.add-vague-step
service: global_chat
judges: [general, openfn_workflow_expert]
---

# notes

From the workflow overview the user asks to add a step but is vague about what
it should actually do ("back up the data somewhere") — no destination, no
format, nothing concrete to write code against. The right move is to add the
step to the structure and wire it into the flow, leaving the body empty or as a
placeholder, then ask the user for the missing detail. It is fine for this to go
straight to the workflow agent (structure only). The assistant should NOT invent
a backup destination or write speculative job code, and should follow up asking
where/how the data should be backed up.

# quality_criteria

- A new step is added to the workflow and connected into the flow (placed sensibly at the end, e.g. after post-to-api).
- The new step's body is left empty or the canonical `// Add operations here` placeholder — no concrete backup/archiving code is invented, since the user never said where or how to back up the data. (A reasonable clarifying question instead of a guessed destination also satisfies this.)
- The existing read-sheet and post-to-api step bodies are not rewritten or given new logic.

# settings

## page

workflows/sheet-to-api-sync

## workflow_yaml

```yaml
name: sheet-to-api-sync
jobs:
  read-sheet:
    id: job-read-sheet-id
    name: Read Spreadsheet
    adaptor: "@openfn/language-googlesheets@4.1.1"
    body: |
      getValues(state.configuration.spreadsheetId, 'Submissions!A2:E');
      fn(state => {
        const rows = state.data?.values || [];
        return { ...state, rows };
      });
  post-to-api:
    id: job-post-api-id
    name: Post Rows to API
    adaptor: "@openfn/language-http@7.3.1"
    body: |
      each(
        $.rows,
        post('https://intake.example.org/rows', state => ({
          body: {
            ref: state.data[0],
            name: state.data[1],
            value: state.data[2]
          }
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 7 * * *"
    enabled: true
edges:
  cron->read-sheet:
    id: edge-cron-read
    source_trigger: cron
    target_job: read-sheet
    condition_type: always
    enabled: true
  read-sheet->post-to-api:
    id: edge-read-post
    source_job: read-sheet
    target_job: post-to-api
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-multi-step-add-vague-step-0004

# turn

## role

user

## content

Can you add a step on the end to back up the data somewhere? I don't want to lose it if the API call goes wrong.
