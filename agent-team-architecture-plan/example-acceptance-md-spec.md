---
id: global-chat.long-yaml.bulk-email-addition
service: global_chat
runs: 1
---

# notes

Long workflow YAML plus multi-turn history. The user has incrementally built up a 9-job pipeline over 5 turns. They now ask for one final addition (Mailgun bulk email after the Asana update). The service should preserve every existing job and edge and add the new step in the right position. Tests that the response is not truncated and that no structure is dropped.

# quality_criteria

- The new bulk-email step is plausibly integrated into the existing pipeline, positioned after the Asana update as the user requested.
- The response language acknowledges that the user has been iterating and treats this as a final tweak, not a fresh start.

# settings

## page

workflows/Data-Integration-and-Reporting/Update-asana

## workflow_yaml

```yaml
name: Data-Integration-and-Reporting
jobs:
  Retrieve-Google-Sheets-Data:
    id: job-retrieve-gsheets
    name: Retrieve Google Sheets Data
    adaptor: "@openfn/language-googlesheets@latest"
    body: // PLACEHOLDER 1
  Retrieve-NetSuite-Data:
    id: job-retrieve-netsuite
    name: Retrieve NetSuite Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 2
  Retrieve-Ferntech-Data:
    id: job-retrieve-ferntech
    name: Retrieve Ferntech Data
    adaptor: "@openfn/language-http@latest"
    body: // PLACEHOLDER 3
  Process-Combined-Data:
    id: job-process-combined
    name: Process Combined Data
    adaptor: "@openfn/language-common@latest"
    body: // PLACEHOLDER 4
  Send-Email-Report:
    id: job-send-email
    name: Send Email Report
    adaptor: "@openfn/language-gmail@latest"
    body: // PLACEHOLDER 5a
  write-to-sheet:
    id: job-write-sheet
    name: write to sheet
    adaptor: "@openfn/language-googlesheets@3.0.13"
    body: // PLACEHOLDER 5b
  Summarise-with-claude:
    id: job-summarise-claude
    name: Summarise with claude
    adaptor: "@openfn/language-claude@1.0.7"
    body: // PLACEHOLDER 5c
  Email-summary:
    id: job-email-summary
    name: Email summary
    adaptor: "@openfn/language-gmail@1.3.0"
    body: // PLACEHOLDER 6
  Update-asana:
    id: job-update-asana
    name: Update asana
    adaptor: "@openfn/language-asana@4.1.0"
    body: // PLACEHOLDER 7
  error-handler:
    id: job-error-handler
    name: Error Handler
    adaptor: "@openfn/language-common@latest"
    body: // Log error and stop workflow
triggers:
  webhook:
    id: trigger-webhook
    type: webhook
    enabled: false
edges:
  webhook->Retrieve-Google-Sheets-Data:
    id: edge-webhook-gsheets
    source_trigger: webhook
    target_job: Retrieve-Google-Sheets-Data
    condition_type: always
    enabled: true
  Retrieve-Google-Sheets-Data->Retrieve-NetSuite-Data:
    id: edge-gsheets-netsuite
    source_job: Retrieve-Google-Sheets-Data
    target_job: Retrieve-NetSuite-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-NetSuite-Data->Retrieve-Ferntech-Data:
    id: edge-netsuite-ferntech
    source_job: Retrieve-NetSuite-Data
    target_job: Retrieve-Ferntech-Data
    condition_type: on_job_success
    enabled: true
  Retrieve-Ferntech-Data->Process-Combined-Data:
    id: edge-ferntech-combined
    source_job: Retrieve-Ferntech-Data
    target_job: Process-Combined-Data
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Send-Email-Report:
    id: edge-combined-email
    source_job: Process-Combined-Data
    target_job: Send-Email-Report
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->write-to-sheet:
    id: edge-combined-sheet
    source_job: Process-Combined-Data
    target_job: write-to-sheet
    condition_type: on_job_success
    enabled: true
  Process-Combined-Data->Summarise-with-claude:
    id: edge-combined-summarise
    source_job: Process-Combined-Data
    target_job: Summarise-with-claude
    condition_type: on_job_success
    enabled: true
  Summarise-with-claude->Email-summary:
    id: edge-summarise-email
    source_job: Summarise-with-claude
    target_job: Email-summary
    condition_type: on_job_success
    enabled: true
  Email-summary->Update-asana:
    id: edge-email-asana
    source_job: Email-summary
    target_job: Update-asana
    condition_type: on_job_success
    enabled: true
  Retrieve-Google-Sheets-Data->error-handler:
    source_job: Retrieve-Google-Sheets-Data
    target_job: error-handler
    condition_type: on_job_failure
    enabled: true
  Retrieve-NetSuite-Data->error-handler:
    source_job: Retrieve-NetSuite-Data
    target_job: error-handler
    condition_type: on_job_failure
    enabled: true
  Retrieve-Ferntech-Data->error-handler:
    source_job: Retrieve-Ferntech-Data
    target_job: error-handler
    condition_type: on_job_failure
    enabled: true
```

## attachments

```json
[
  {
    "type": "log",
    "content": "[2026-05-12T14:08:11Z] INFO  Retrieve-Google-Sheets-Data succeeded\n[2026-05-12T14:08:12Z] INFO  Retrieve-NetSuite-Data succeeded\n[2026-05-12T14:08:13Z] INFO  Retrieve-Ferntech-Data succeeded\n[2026-05-12T14:08:14Z] INFO  Process-Combined-Data succeeded (412 records)\n[2026-05-12T14:08:15Z] INFO  Send-Email-Report succeeded\n[2026-05-12T14:08:15Z] INFO  write-to-sheet succeeded\n[2026-05-12T14:08:17Z] INFO  Summarise-with-claude succeeded\n[2026-05-12T14:08:18Z] INFO  Email-summary succeeded\n[2026-05-12T14:08:19Z] WARN  Update-asana: HTTP 502 from api.asana.com, retrying (1/3)\n[2026-05-12T14:08:21Z] INFO  Update-asana succeeded on retry\n[2026-05-12T14:08:21Z] INFO  Run complete, 9 jobs, 0 failures"
  },
  {
    "type": "run_output",
    "content": "{\"recordsProcessed\": 412, \"asanaTaskIds\": [\"1209384756\", \"1209384757\", \"1209384758\"], \"summary\": \"412 records merged from 3 sources, summary emailed, Asana updated\"}"
  }
]
```

# history

## turn

### role

user

### content

I need to create a comprehensive data integration workflow that pulls data from Google Sheets, NetSuite, and Ferntech, then processes everything together and creates various reports and notifications.

## turn

### role

assistant

### content

Absolutely! Let's start by setting up the workflow to retrieve data from Google Sheets, NetSuite, and Ferntech. I'll create jobs for each data source and connect them in sequence.

```yaml
# 3 jobs: Retrieve-Google-Sheets-Data, Retrieve-NetSuite-Data, Retrieve-Ferntech-Data
# webhook trigger, sequential edges
```

## turn

### role

user

### content

Once the data is retrieved, I want to process all the combined data together before generating any reports.

## turn

### role

assistant

### content

Great, I'll add a processing job that takes the output from the three data retrieval jobs and combines the data for further use.

```yaml
# adds Process-Combined-Data after the three retrieval jobs
```

## turn

### role

user

### content

After processing, I want to send an email report and also write the results back to a Google Sheet.

## turn

### role

assistant

### content

Understood. I'll add two jobs: one to send an email report and another to write the processed data to a Google Sheet. Both will run after the processing step.

```yaml
# adds Send-Email-Report and write-to-sheet branching from Process-Combined-Data
```

## turn

### role

user

### content

Can we also use Claude AI to summarize the processed data, then email that summary, and update our Asana project with the results?

## turn

### role

assistant

### content

Excellent idea! I'll add a summarization job using Claude AI, followed by jobs to email the summary and update Asana. These will branch off after the processing step as well.

```yaml
# adds Summarise-with-claude, Email-summary, Update-asana
```

## turn

### role

user

### content

Can you make sure the workflow is robust to errors in any of the data retrieval steps?

## turn

### role

assistant

### content

Good point! I'll add error handling so that if any data retrieval job fails, the workflow will log the error and stop further processing.

```yaml
# adds error-handler job and on_job_failure edges from each retrieval job
```

# turn

## role

user

## content

Perfect! One final addition. After updating Asana, I want to format the data for bulk emailing and then send out bulk emails using Mailgun.
