---
id: workflow-chat.long-yaml
service: workflow_chat
judges: [general, openfn_workflow_expert]
---

# notes

Long workflow YAML plus multi-turn history. The user has incrementally built up a 9-job pipeline over 5 turns. They now ask for one final addition (Mailgun bulk email after the Asana update). The service should preserve every existing job and edge and add the new step in the right position. Tests that the response is not truncated and that no structure is dropped.

# quality_criteria

- The new bulk-email step is plausibly integrated into the existing pipeline, positioned after the Asana update as the user requested.

# settings

## existing_yaml

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

Absolutely! Let's start by setting up the workflow to retrieve data.

## turn

### role

user

### content

Once the data is retrieved, I want to process all the combined data together.

## turn

### role

assistant

### content

Great, I'll add a processing job.

## turn

### role

user

### content

After processing, I want to send an email report and also write the results back to a Google Sheet.

## turn

### role

assistant

### content

Understood. Added Send-Email-Report and write-to-sheet.

## turn

### role

user

### content

Can we also use Claude AI to summarize the processed data, then email and update Asana?

## turn

### role

assistant

### content

Excellent — added Summarise-with-claude, Email-summary, Update-asana.

## turn

### role

user

### content

Can you make sure the workflow is robust to errors in any of the data retrieval steps?

## turn

### role

assistant

### content

Added an error-handler with on_job_failure edges from each retrieval job.

# turn

## role

user

## content

Perfect! One final addition - after updating Asana, I want to format the data for bulk emailing and then send out bulk emails using Mailgun.
