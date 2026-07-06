---
id: global-chat.ai-application-verification-chatgpt
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: a program manager at a health-grants organisation wants
a recurring workflow that reads incoming grant applications from a Google
Sheet, uses AI web research to verify that each applicant's healthcare site is
a real, legitimate facility, and writes an approve/decline recommendation with
a confidence rating and notes back to the sheet. The request is realistic and
underspecified: it names no adaptor, no AI model or provider, no exact columns,
no schedule, and no output format. A strong answer fills these gaps with
sensible defaults (or surfaces the key ambiguities) while producing a coherent
multi-step workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce
it exactly. Adaptor names and versions, job names, the prompt wording, the AI
model choice, the exact columns, and the schedule can all legitimately differ.
It is provided so the judge has a concrete sense of the shape, step breakdown,
and capabilities a high-quality answer covers. Judge against the
quality_criteria, using the model answer only as a reference for what "good"
looks like, not as a string to diff against.

## Model answer (reference only — do not require exact replication)

```yaml
name: AI Application Verification - ChatGPT
jobs:
  Get-Applications:
    name: Get Applications
    adaptor: "@openfn/language-googlesheets@3.0.17"
    body: |
      //Get applications from source google sheet
      getValues('1xuIwyA6_EsFJ6wGINduJLmx3tC1NZK9zdZ9Oe3-KqmA', //sheet id
        'applications!A:E'); //sheet range
  Research-Site:
    name: Research Site
    adaptor: "@openfn/language-chatgpt@2.0.0"
    body: >-
      fn(state => {
        //save relevant application data
        state.applicantsData = state.data.values
          .slice(1)
          .reduce((acc, [applicationId, applicationName, site, country]) => {
            acc.push({
              applicationId,
              applicationName,
              site,
              country,
            });
            return acc;
          }, []);
        state.results = [];
        return state;
      });


      each('$.applicantsData[*]', //for each applicant, let's send prompt to
      chatgpt...
        //prompt we created and tested with chatgpt deepResearch...
        //...that we'll dynamically populate with the source application data
        deepResearch(state => `Verify if applicant's healthcare site is legitimate using web search.
          INPUT:  ${JSON.stringify(state.data)}
          VERIFICATION CRITERIA:

          Confirm site exists as legitimate healthcare facility
          Assess online presence (website/Facebook/none)
          If website exists: evaluate design quality, functionality, mission statements, funding sources

          OUTPUT: Return input data as JSON with added properties:

          "siteVerificationStatus": "Pre-Approved" (high confidence legitimate healthcare facility) or "Declined" (low confidence)
          "orgType": "private", "government", "not-for-profit", or "unknown"
          "fundingStatus": funding sources if identified, or "unknown"
          "siteVerificationNotes": Summary of search findings and reasoning for verification decision,
          "confidenceLevel": Confidence level on the  appprove/disapprove answer. 0-5. 0 is the lowest and 5 is the highest

          Example:
          json{
            "applicationId": "001",
            "applicationName": "OpenFn",
            "site": "Nsawam Government Hospital",
            "country": "Ghana",
            "siteVerificationStatus": "Pre-Approved",
            "orgType": "government",
            "fundingStatus": "government-funded",
            "siteVerificationNotes": "Hospital confirmed to exist in Nsawam, Ghana. Has professional website with service information and contact details. Government facility with established online presence."
          "confidenceLevel":5
          }
          Return JSON only, no additional text.`, {
        model: 'o3-deep-research', //chatgpt model
        max_tool_calls: 1 //controls the total number of tool calls the model will make before returning a result
      }).then(state => {
        //now we format the response from chatgpt...
        const outputText = state.data.output_text;
        const jsonString = outputText.replace(/^```json\s*|\s*```$/g, '');
        const result = JSON.parse(jsonString);
        state.results.push(result);
        return state
      }))
  Update-Application:
    name: Update Application
    adaptor: "@openfn/language-googlesheets@3.0.17"
    body: >-
      fn(state => {

        state.rows = state.results.reduce((acc, item) => {
          const {
            applicationId,
            applicationName,
            site,
            country,
            confidenceLevel,
            siteVerificationStatus,
            siteVerificationNotes
          } = item;

          acc.push([
            applicationId,
            applicationName,
            site,
            country,
            confidenceLevel,
            siteVerificationStatus,
            siteVerificationNotes
          ]);

          return acc;
        }, []);

        //columns to update in google sheet with results
        state.rows.unshift([
          "Application ID",
          "Applicant Name",
          "Site",
          "Country",
          "Confidence Level",
          "Site Verification Status",
          "Site Verification Notes"
        ]);

        return state;
      })


      //batch update google sheet with results

      batchUpdateValues({
        spreadsheetId: '1xuIwyA6_EsFJ6wGINduJLmx3tC1NZK9zdZ9Oe3-KqmA', //sheet id
        range: 'Updates!A:G', //range to update
        values: $.rows
      })
triggers:
  cron:
    type: cron
    enabled: true
    cron_expression: 0 0 * * *
    cron_cursor_job: null
edges:
  cron->Get-Applications:
    condition_type: always
    enabled: true
    target_job: Get-Applications
    source_trigger: cron
  Get-Applications->Research-Site:
    condition_type: on_job_success
    enabled: true
    target_job: Research-Site
    source_job: Get-Applications
  Research-Site->Update-Application:
    condition_type: on_job_success
    enabled: true
    target_job: Update-Application
    source_job: Research-Site
```

# quality_criteria

- The response produces a coherent multi-step workflow covering the full pipeline: read grant/program applications from a Google Sheet, run an AI verification step over each applicant's healthcare site, and write the results back to the sheet on a schedule.
- The verification step uses an AI/LLM adaptor (e.g. the chatgpt adaptor) with a model capable of web research, and the workflow iterates per applicant (e.g. each() over the parsed application rows) rather than sending one undifferentiated blob.
- The AI prompt is well-constructed: it injects each applicant's data, states the verification criteria (does the site exist as a legitimate healthcare facility, what is its online presence), and asks for structured JSON output including a verification status/decision, an organisation type, a confidence level, and notes/reasoning for the decision.
- The AI response is parsed robustly (e.g. stripping code fences before JSON.parse) and per-applicant results are accumulated on state for the write-back step.
- The write-back step records the results to the spreadsheet with appropriate columns (applicant identity plus the verification decision, confidence, and notes), using a suitable googlesheets write function.
- The workflow handles the realistic ambiguities the user left open, either making sensible, clearly stated default choices (columns, sheet ranges, AI model, schedule) or surfacing them as assumptions/clarifying points, rather than silently ignoring them.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, job names, prompt wording, columns, and schedule may all legitimately differ).

# turn

## role

user

## content

I manage a small grants program that funds community health clinics, and applications come into a Google Sheet with the applicant's name, the clinic they run, and their country. Right now someone on my team manually googles every clinic to check it actually exists before we shortlist anyone, and it takes forever. Could we set something up where AI does that web research for us, checks whether each clinic seems to be a real, legitimate facility with some kind of online presence, and gives us an approve or decline recommendation along with how confident it is and a short note explaining why? Ideally it would write all of that back into the sheet and just run once a day on its own.
