---
id: global-chat.gmail-to-claude-to-googlesheets
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: an operations person with a busy shared inbox wants a
recurring workflow that fetches new Gmail messages (optionally filtered by
sender), asks an AI to score each email's urgency/importance, and appends the
scored emails to a Google Sheet the team can triage from. The request is
realistic and underspecified: it names no adaptors, no LLM, no sheet layout, no
cron expression, and no mechanism for "only new mail". A strong answer fills
these gaps with sensible defaults (or surfaces the key ambiguities) while
producing a coherent multi-step workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce
it exactly. Adaptor versions, the prompt wording sent to the LLM, the choice of
LLM model, the sheet layout and range, the cursor / last-synced-date handling,
and the exact schedule can all legitimately differ. It is provided so the judge
has a concrete sense of the shape, step breakdown, and capabilities a
high-quality answer covers. Judge against the quality_criteria, using the model
answer only as a reference for what "good" looks like, not as a string to diff
against.

## Model answer (reference only — do not require exact replication)

```yaml
name: Gmail to Claude to GoogleSheets
jobs:
  Setup-Workflow:
    name: Setup Workflow
    adaptor: "@openfn/language-common@2.4.0"
    body: |-
      // Configuration required for this workflow to run
      // You should insert your own values here in
      // order for this workflow to run
      fn(state => {
        // Set the ID of the sheet you want to upload results to
        state.spreadsheetId = '1WdlmQXve0Fd-V32rNka_yss0OfFkesbDp_MKjA32hWo',


        // Set the sheet name and column range to upload to
        state.range = 'Sheet1!A1:E1';

        // Set a query to search the gmail inbox for
        // This query will find all emails from support@openfn.org
        state.searchQuery = "from:support@openfn.org";

        // Set the date to search emails from
        // Only emails received AFTER this date will be included in the search
        state.lastSyncedDate = "2025-04-30T00:00:00Z";

        return state;
      })
  Identify-Important-Emails:
    name: Identify Important Emails
    adaptor: "@openfn/language-claude@1.0.7"
    body: >-

      // Using claude to get the most important emails based on their subject
      and to add an importance_score to each

      prompt(state =>

      `Score each email 1-10 for importance (10=highest)

      based on urgency and relevance (impact on recipient).

      Consider subject, sender, and date.

      Sort by score (highest first), add “importance_score” field to each
      object.

      Input emails: ${JSON.stringify(state.data)}

      Return sorted array with importance_score added to each object.

      Return only the JSON array.

      Do NOT include any explanation, text, or code block formatting (like
      'json').

      Just the raw JSON array.`,
        {
          model: 'claude-3-7-sonnet-20250219',
          max_tokens: 15000,
        });

      // Parsing the result from claude to an array of objects for the next job

      fn(state => {
        const { content } = state.data;
        state.emails = JSON.parse(content[0].text);
        return state;
      })
  Add-to-GSheets:
    name: Add to GSheets
    adaptor: "@openfn/language-googlesheets@3.0.13"
    body: >+
      // Map email response from claude to match gsheets format

      fn(state => {
        state.gsheetsData = state.emails.map(email => {
          return [email.messageId, email['from'], email.subject, email.date, email.importance_score]
        })
        return state;
      })


      // Append mapped valued to gsheets

      appendValues({
        spreadsheetId: $.spreadsheetId,
        range: $.range,
        values: $.gsheetsData,
      })

  Get-Emails:
    name: Get Emails
    adaptor: "@openfn/language-gmail@1.2.0"
    body: >+
      // Ensure you add your credentials before running these jobs

      // This job is fetching emails from Gmail with queries of the sender and
      the date received



      // Formatting the date input to match gmail's date format

      function formatDate(date) {
        const dateObj = new Date(date);
        return `${dateObj.getFullYear()}/${dateObj.getMonth() + 1}/${dateObj.getDate()}`;
      }


      // Add lastSyncedDate to cursor

      cursor($.cursor, { defaultValue: state => state.lastSyncedDate ||
      '2025-04-30T00:00:00Z' })



      getContentsFromMessages(
        {
          // Search query and lastSyncDate are your inputs. Change them to your own values
          query: state => `${state.searchQuery} after:${formatDate(state.cursor)}`,
          contents: [ // The contents of the result
            'from',
            'subject',
            'date',
          ],
          maxResults: 50
        }
      ).then(state => {
        // Update the cursor with the latest received date
        state.cursor = state.data?.[0]?.date;
        return state
      })
triggers:
  cron:
    type: cron
    enabled: false
    cron_expression: 00 * * * *
    cron_cursor_job: null
edges:
  cron->Setup-Workflow:
    condition_type: always
    enabled: true
    target_job: Setup-Workflow
    source_trigger: cron
  Identify-Important-Emails->Add-to-GSheets:
    condition_type: js_expression
    enabled: true
    target_job: Add-to-GSheets
    source_job: Identify-Important-Emails
    condition_label: Email score added
    condition_expression: "!state.errors && state.emails.length > 0"
  Setup-Workflow->Get-Emails:
    condition_type: on_job_success
    enabled: true
    target_job: Get-Emails
    source_job: Setup-Workflow
  Get-Emails->Identify-Important-Emails:
    condition_type: on_job_success
    enabled: true
    target_job: Identify-Important-Emails
    source_job: Get-Emails
```

# quality_criteria

- The response produces a coherent multi-step workflow covering the full pipeline: fetch emails from Gmail, score them with an LLM, and append the scored results to a Google Sheet, running on a recurring schedule (e.g. an hourly cron trigger).
- The Gmail step filters messages with a search query (e.g. by sender) combined with a date bound so each run only processes mail received since the last run — some form of cursor or last-synced-date handling, updated after fetching — rather than re-reading the whole inbox every time.
- The workflow extracts the relevant fields from each message (e.g. from, subject, date) rather than passing raw payloads downstream.
- The LLM step sends the batch of emails with a prompt that asks for an importance/urgency score per email and structured JSON back (ideally sorted by score), and the response is parsed defensively into an array on state for the next step (not left as raw LLM output).
- The sheet step maps scored emails into rows matching a column layout and appends them to a configured spreadsheet/range, and the append is guarded on the LLM step actually producing results (e.g. an edge condition or check that the parsed email list is non-empty and error-free).
- Configuration the user will need to change (spreadsheet ID, range, search query, starting date) is clearly separated and easy to find and edit, whether in a dedicated setup step or clearly-commented constants.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, prompt wording, LLM model choice, sheet layout, cursor mechanics, and schedule may all legitimately differ).

# turn

## role

user

## content

Our team shares an ops inbox that gets flooded every day and important stuff keeps getting buried. I'd love something that runs every hour or so, grabs any new messages we haven't seen yet (honestly mostly just the ones from a couple of key senders), has an AI rate how urgent or important each one is, and then drops them into a Google Sheet sorted by importance so whoever's on triage can just work down the list. It shouldn't keep re-adding emails it already logged from previous runs.
