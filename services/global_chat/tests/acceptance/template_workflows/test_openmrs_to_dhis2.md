---
id: global-chat.openmrs-to-dhis2
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: an M&E / health-informatics user runs OpenMRS at their
clinic and reports monthly aggregate HIV indicators (positive tests, tests
performed) into a national DHIS2 instance by hand. They want a workflow that
pulls the month's patient encounters from OpenMRS, tallies the indicators from
the encounter observations, and pushes the aggregate numbers to DHIS2, only
syncing new records each run. The request is realistic and underspecified: it
names no adaptors, no API endpoints, no concept UUIDs, no DHIS2 data element
IDs, and no schedule. A strong answer fills these gaps with sensible defaults
(or surfaces the key ambiguities) while producing a coherent multi-step
workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce
it exactly. Adaptor versions, concept UUIDs, data element IDs, org unit IDs,
variable names, the exact schedule, and the prose can all differ. It is
provided so the judge has a concrete sense of the shape, step breakdown, and
capabilities a high-quality answer covers. Judge against the quality_criteria,
using the model answer only as a reference for what "good" looks like, not as
a string to diff against.

## Model answer (reference only — do not require exact replication)

```yaml
name: OpenMRS to DHIS2
jobs:
  Fetch-Encounters:
    name: Fetch Encounters
    adaptor: "@openfn/language-openmrs@5.0.2"
    body: >+

      // Update the credentials for OpenMRS before running this job

      // Update the variables with your values


      http.get("/ws/rest/v1/encounter", {
        query: {
          v: 'full',
          q: 'Gere', // This will search for patients with a given surname
          fromdate: state => state.lastSyncedDate?.split('T')[0] // synced date is a timestap and we need `yyyy-mm-dd`
        },
      })


      // Storing today's date in lastSyncDate for the next run

      cursor('now', { key: 'lastSyncedDate' })


  Map-encounter:
    name: Map encounter
    adaptor: "@openfn/language-common@latest"
    body: >-
      // Map encounter.obs data from OpenMRS to some HIV indicators on DHIS2

      // We are aggregating based on the OpenMRS concept uuid that corresponds
      to HIV related observations

      fn(state => {
        const dataElementMap = {
          HIV_POSITIVE_CASES: {
            counter: 0,
            dataElementId: "bmW8ktueArb", // DE corresponding to HIV Positive cases on DHIS2
            period: null
          },
          HIV_TESTS_PERFORMED: {
            counter: 0,
            dataElementId: "LicY0q8cagk", // DE corresponding to HIV Tests Performed on DHIS2
            period: null
          }
        };



        // Process each encounter in the results array from OpenMRS
        // OpenMRS encounters represent patient visits or clinical events
        state.data.results.forEach(result => {
          const period = dateFns.format(new Date(result.encounterDatetime), 'yyyyMM'); // Convert date to DHIS2 period format: 202504

          // Count occurrences in observation data
          result.obs.forEach(curr => {
            // Count HIV positive cases from the encounter observations
            // We look for specific concept UUIDs that indicate HIV test results
            if (curr.concept.uuid === "4c2a4b12-becc-4429-a94d-b78e06699d0f" && curr.display.includes('Positive')) {
              dataElementMap.HIV_POSITIVE_CASES.period = period
              dataElementMap.HIV_POSITIVE_CASES.counter++;
            }
            // Count HIV tests performed during this encounter
            // We check for observations that indicate a test was conducted
            else if (curr.display.includes('Yes')) {
              dataElementMap.HIV_TESTS_PERFORMED.period = period
              dataElementMap.HIV_TESTS_PERFORMED.counter++;
            }
          });
        });

        // Prepare data for DHIS2 by creating data value sets
        // Only add non-zero counts to avoid reporting empty values

        const dataValueSets = Object.values(dataElementMap)
          .filter(dataElement => dataElement.counter > 0)
          .map((dataElement) => ({
            // Each data value requires a data element ID, period, org unit, and value
            dataElement: dataElement.dataElementId,
            period: dataElement.period,
            orgUnit: "DiszpKrYNg8",
            value: dataElement.counter
          })
          );


        // Add all our prepared data values to the state for the next workflow step
        return { ...state, dataValueSets };
      })
  Create-Indicators:
    name: Create Indicators
    adaptor: "@openfn/language-dhis2@6.3.4"
    body: >-
      // Create dataValueSets that were mapped from previous step in dhis2

      // the create function is reading dataValueSets from state:
      $.dataValueSets

      create('dataValueSets', {
        dataValues: $.dataValueSets
      });
triggers:
  cron:
    type: cron
    enabled: false
    cron_expression: 00 00 01 * *
    cron_cursor_job: null
edges:
  cron->Fetch-Encounters:
    condition_type: always
    enabled: true
    target_job: Fetch-Encounters
    source_trigger: cron
  Fetch-Encounters->Map-encounter:
    condition_type: on_job_success
    enabled: true
    target_job: Map-encounter
    source_job: Fetch-Encounters
  Map-encounter->Create-Indicators:
    condition_type: js_expression
    enabled: true
    target_job: Create-Indicators
    source_job: Map-encounter
    condition_label: Indicators present
    condition_expression: "!state.errors && state.dataValueSets.length > 0"
```

# quality_criteria

- The response produces a coherent multi-step workflow that covers the full pipeline: fetch patient encounters from OpenMRS, transform and aggregate the encounter observations into indicator counts, and push the aggregates to DHIS2.
- The OpenMRS fetch includes some incremental-sync mechanism (e.g. a cursor or stored last-synced date used to filter the query) so each run only pulls new encounters rather than re-fetching everything.
- The transformation step aggregates encounter observations into counts for the HIV indicators (e.g. HIV positive cases and HIV tests performed), keying the counting on concept identifiers from the observations, and derives a DHIS2-style period (e.g. yyyyMM) from the encounter date.
- The aggregates are shaped as DHIS2 dataValueSets, with each data value carrying a data element ID, period, org unit, and value, and zero counts are skipped rather than reported as empty values.
- The final step pushes the data to DHIS2 via `create('dataValueSets', ...)` (or a functionally equivalent DHIS2 adaptor call), and is guarded so it only runs when there is data to send (e.g. an edge condition checking that dataValueSets is non-empty).
- The response acknowledges the placeholders and assumptions the user must fill in (OpenMRS concept UUIDs, DHIS2 data element IDs, org unit ID, credentials) rather than presenting invented identifiers as authoritative values.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, concept UUIDs, data element IDs, variable names, and schedule may all legitimately differ).

# turn

## role

user

## content

Hi, I do M&E for a clinic where we run OpenMRS as our medical record system. Every month I have to report our HIV numbers, like how many tests we did and how many came back positive, into the national DHIS2 instance, and right now I count everything up and type it in by hand. Could you build me a workflow that pulls the month's patient encounters from OpenMRS, tallies up those indicators, and sends the aggregate numbers to DHIS2? Ideally it should only pick up new records each time it runs so we're not recounting old encounters.
