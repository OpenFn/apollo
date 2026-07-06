---
id: global-chat.dhis2-to-postgres
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: a data/BI person at a health program wants a recurring
workflow that pulls monthly indicator values (vaccine/antigen consumption) from
the DHIS2 analytics API and lands them in their own Postgres database for
dashboards and reporting. The target table might not exist yet on the first run,
so it should be created automatically if missing. The request is realistic and
underspecified: it names no adaptors, no analytics dimension syntax, no table or
column names, and no exact schedule. A strong answer fills these gaps with
sensible defaults (or surfaces the key ambiguities) while producing a coherent
multi-step workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce it
exactly. Adaptor versions, table and column names, variable names, the exact
schedule, and the prose can all differ. It is provided so the judge has a
concrete sense of the shape, step breakdown, and capabilities a high-quality
answer covers. Judge against the quality_criteria, using the model answer only as
a reference for what "good" looks like, not as a string to diff against.

## Model answer (reference only — do not require exact replication)

```yaml
name: DHIS2 To Postgres
jobs:
  Add-data-elements-to-state:
    name: Add data elements to state
    adaptor: "@openfn/language-common@2.4.0"
    body: >-
      fn(state => {
        let dataElementString = state.configuration.dataElements.map(item => `${item.id}.${item.combinationId}`).join(';');

        const now = new Date();
        const yearMonth = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}`

        dataElementString = 'dx:' + dataElementString + `,pe:${yearMonth}`

        const ouFilter = state.configuration.ouFilter;


        return { ...state, dataElementString, ouFilter }
      })
  Transform-data:
    name: Transform data
    adaptor: "@openfn/language-common@latest"
    body: >-
      fn(state => {
        const valueIndex = state.data.headers.findIndex(header=> header.column === 'Value');
        const dataIndex = state.data.headers.findIndex(header=> header.column === 'Data');


        const dataObjects = state.data.rows.map(row => ({
          name: state.configuration.dataElements.find(dataElementObject => `${dataElementObject.id}.${dataElementObject.combinationId}` === row[dataIndex])['name'],
          value: row[valueIndex]
        }))



        return { ...state, formattedTableData: dataObjects }
      })
  Check-if-table-exists-in-database:
    name: Check if table exists in database
    adaptor: "@openfn/language-postgresql@6.0.12"
    body: describeTable('monthly_consumption_of_antigens')
  Get-Indicators-values-from-DHIS2:
    name: Get Indicators values from DHIS2
    adaptor: "@openfn/language-dhis2@6.3.4"
    body: |-
      get('analytics', {
        dimension: $.dataElementString,
        filter: $.ouFilter,
        displayProperty: 'NAME',
        includeNumDen: false,
        skipMeta: true,
        skipData: false,
      });
  Create-table-if-absent:
    name: Create table if absent
    adaptor: "@openfn/language-postgresql@6.0.12"
    body: |-

      fn(state => {
        const columns = [
          {
            name: 'name',
            type: 'varchar',
            required: true,
            unique: false
          },
          {
            name: 'value',
            type: 'integer',
            required: true,
            unique: false
          },
        ];

        return { ...state, columns }
      })


      insertTable('monthly_consumption_of_antigens', state => state.columns);
  Update-postgres:
    name: Update postgres
    adaptor: "@openfn/language-postgresql@6.0.12"
    body: "insertMany('monthly_consumption_of_antigens', state =>
      state.formattedTableData, { setNull: \"'undefined'\", logValues: true });"
triggers:
  cron:
    type: cron
    enabled: false
    cron_expression: 00 00 * * 01
    cron_cursor_job: null
edges:
  cron->Add-data-elements-to-state:
    condition_type: always
    enabled: true
    target_job: Add-data-elements-to-state
    source_trigger: cron
  Transform-data->Check-if-table-exists-in-database:
    condition_type: on_job_success
    enabled: true
    target_job: Check-if-table-exists-in-database
    source_job: Transform-data
  Add-data-elements-to-state->Get-Indicators-values-from-DHIS2:
    condition_type: on_job_success
    enabled: true
    target_job: Get-Indicators-values-from-DHIS2
    source_job: Add-data-elements-to-state
  Get-Indicators-values-from-DHIS2->Transform-data:
    condition_type: on_job_success
    enabled: true
    target_job: Transform-data
    source_job: Get-Indicators-values-from-DHIS2
  Check-if-table-exists-in-database->Create-table-if-absent:
    condition_type: js_expression
    enabled: true
    target_job: Create-table-if-absent
    source_job: Check-if-table-exists-in-database
    condition_label: Table doesn't exist
    condition_expression: state.data.length === 0
  Check-if-table-exists-in-database->Update-postgres:
    condition_type: js_expression
    enabled: true
    target_job: Update-postgres
    source_job: Check-if-table-exists-in-database
    condition_label: Table exists
    condition_expression: state.data.length > 0
  Create-table-if-absent->Update-postgres:
    condition_type: on_job_success
    enabled: true
    target_job: Update-postgres
    source_job: Create-table-if-absent
```

# quality_criteria

- The response produces a coherent multi-step workflow covering the full pipeline: build the DHIS2 analytics query from the configured data elements plus the current reporting period (e.g. yyyyMM), fetch the values, transform them, ensure the Postgres table exists, and insert the rows.
- The DHIS2 step queries the analytics API with dimension/filter parameters (data element dimension string, period, and an org unit filter) rather than fetching raw events or inventing an unrelated endpoint.
- The transform step converts the analytics rows/headers table shape into named records (e.g. name/value objects), mapping data element IDs back to human-readable names instead of storing bare UIDs.
- The workflow checks whether the target Postgres table exists and creates it only when absent, using conditional branching (e.g. a describeTable-style check with js_expression edges on the result, or an equivalent create-if-missing approach) so repeat runs don't fail or re-create the table.
- The transformed rows are inserted into Postgres with an appropriate bulk operation (e.g. insertMany), and the workflow runs on a recurring schedule (weekly or monthly cron) rather than requiring manual triggering.
- Environment-specific values (data element IDs, org unit filter, table name) are kept as configuration/placeholders or clearly flagged as values the user must supply, rather than invented IDs presented as authoritative.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, table/column names, variable names, and schedule may all legitimately differ).

# turn

## role

user

## content

Hi, I do the reporting for our immunization program and every month I have to log into DHIS2, pull the monthly consumption numbers for a handful of vaccines from the analytics section, and copy them into our own Postgres database that feeds our dashboards. Can you set up something that does this automatically on a schedule, say weekly or monthly? One thing to note: the table in our database might not exist yet the first time this runs, so it should get created automatically if it's missing.
