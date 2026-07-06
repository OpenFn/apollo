---
id: global-chat.dhis2-tracker-to-dhis2-aggregate
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: an M&E officer runs a child-health program that records
individual patient visits in DHIS2 Tracker (infant weights, vaccine doses given,
etc.), but the ministry requires monthly aggregate counts reported into a DHIS2
aggregate dataset. Today someone tallies these numbers by hand each month; the
user wants a workflow that computes the aggregates from the tracker events and
submits them automatically. The request is realistic and underspecified — it
names no adaptor, no function, no program / data element / org unit / dataset
IDs, and no exact indicator definitions. A strong answer fills these gaps with
sensible defaults (or surfaces the key ambiguities) while producing a coherent
fetch → transform → submit workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce it
exactly — adaptor versions, data element / program / org unit IDs, variable
names, period handling, the schedule, and the prose can all differ. It is
provided so the judge has a concrete sense of the shape, step breakdown, and
capabilities a high-quality answer covers. Judge against the quality_criteria,
using the model answer only as a reference for what "good" looks like — not as a
string to diff against.

## Model answer (reference only — do not require exact replication)

```yaml
name: DHIS2 Tracker → DHIS2 Aggregate
jobs:
  Fetch-Tracked-Entity-Events-from-DHIS2:
    name: Fetch Tracked Entity Events from DHIS2
    adaptor: "@openfn/language-dhis2@7.0.0"
    body: >
      // Add your DHIS2 credentials before you run this sample code


      // Fetching events from a specific orgUnit, program, and programStage in
      DHIS2

      tracker.export('events', {orgUnit:'DiszpKrYNg8',  program: 'IpHINAT79UW',
      programStage:'ZzYYXq4fJie'});
  Transform-Events-to-Aggregate-Data:
    name: Transform Events to Aggregate Data
    adaptor: "@openfn/language-common@latest"
    body: >
      // Aggregating the occurence of different conditions in each event's
      dataValues


      fn(state => {
        let infantWeightCount = 0;
        let vitACount = 0;
        let yellowFeverCount = 0;
        let measlesCount = 0;
        state.data.instances.forEach(event => {

          event.dataValues.forEach(dataValue => {
            // Infant Weight (g) dataElement
            if (dataValue.dataElement === 'GQY2lXrypjO' && Number(dataValue.value) >= 2500) {
              infantWeightCount++;
            }

            // Vit A dataElement
            if (dataValue.dataElement === 'HLmTEmupdX0' && dataValue.value === 'true') {
              vitACount++;
            }

            // Yellow fever dose dataElement
            if (dataValue.dataElement === 'rxBfISxXS2U' && dataValue.value === 'true') {
              yellowFeverCount++;
            }

            // Measles dose dataElement
            if (dataValue.dataElement === 'FqlgKAG8HOu' && dataValue.value === 'true') {
              measlesCount++;
            }

          })


        });

        // Createing a dataValueSet payload
        state.dataValueSetPayload = {
          dataSet: 'BfMAe6Itzgt',
          orgUnit: 'DiszpKrYNg8',
          period: '202406',
          completeDate: '2024-06-30',
          dataValues: [
            {
              dataElement: 'NLnXLV5YpZF',
              value: infantWeightCount,
              categoryOptionCombo: 'Prlt0C1RF0s'
            },
            {
              dataElement: 'tU7GixyHhsv',
              value: vitACount,
              categoryOptionCombo: 'Prlt0C1RF0s'
            },
            {
              dataElement: 'l6byfWFUGaP',
              value: yellowFeverCount,
              categoryOptionCombo: 'Prlt0C1RF0s'
            },
            {
              dataElement: 'YtbsuPPo010',
              value: measlesCount,
              categoryOptionCombo: 'Prlt0C1RF0s'
            }
          ]
        };

        return state;
      })
  Submit-Aggregated-Data-to-DHIS2:
    name: Submit Aggregated Data to DHIS2
    adaptor: "@openfn/language-dhis2@7.0.0"
    body: |
      // Create a dataValueSet with the aggregated data
      create("dataValueSets", state=> state.dataValueSetPayload);
triggers:
  cron:
    type: cron
    enabled: true
    cron_expression: 00 00 01 * *
    cron_cursor_job: null
edges:
  cron->Fetch-Tracked-Entity-Events-from-DHIS2:
    condition_type: always
    enabled: true
    target_job: Fetch-Tracked-Entity-Events-from-DHIS2
    source_trigger: cron
  Fetch-Tracked-Entity-Events-from-DHIS2->Transform-Events-to-Aggregate-Data:
    condition_type: on_job_success
    enabled: true
    target_job: Transform-Events-to-Aggregate-Data
    source_job: Fetch-Tracked-Entity-Events-from-DHIS2
  Transform-Events-to-Aggregate-Data->Submit-Aggregated-Data-to-DHIS2:
    condition_type: on_job_success
    enabled: true
    target_job: Submit-Aggregated-Data-to-DHIS2
    source_job: Transform-Events-to-Aggregate-Data
```

# quality_criteria

- The response produces a coherent workflow that covers the full pipeline: fetch tracker events from DHIS2, transform/tally them into aggregate indicator counts, and submit the aggregates back to DHIS2 as a data value set.
- The fetch step retrieves tracker events from DHIS2 scoped to a specific org unit, program, and (ideally) program stage — e.g. via tracker.export or an equivalent DHIS2 adaptor call.
- The transform step iterates over each event's dataValues and tallies counts against specific data elements with sensible conditions — e.g. a numeric threshold for infant weight (such as >= 2500g) and boolean true checks for vaccine doses like Vitamin A, yellow fever, and measles.
- The transform builds a dataValueSet payload containing dataSet, orgUnit, period, and one dataValue per computed indicator (with category option combos where relevant), rather than submitting raw event data.
- The submit step sends the aggregate payload back to DHIS2 via create('dataValueSets', ...) or an equivalent adaptor call.
- The workflow runs on a monthly-style schedule (e.g. a cron trigger at the start or end of each month), matching the user's monthly reporting cadence.
- The response treats specific IDs (program, program stage, data elements, org unit, dataset, category option combos) as placeholders or assumptions the user must replace with their own instance's values, rather than presenting invented IDs as authoritative.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, IDs, variable names, period handling, and schedule may all legitimately differ).

# turn

## role

user

## content

I work as the M&E officer for a child health program and we track all our patient visits in DHIS2 Tracker — each visit records things like the baby's weight and which vaccine doses they got. The problem is the ministry wants monthly totals reported into a DHIS2 aggregate dataset, stuff like how many infants were at a healthy weight and how many received each vaccine dose that month. Right now one of our staff counts everything by hand at the end of the month and types it in, which takes ages and there are always mistakes. Can you set up a workflow that works out these numbers from our tracker data and submits them to the aggregate dataset automatically each month?
