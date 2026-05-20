---
id: job-chat.navigation-workflow-to-job
service: job_chat
judges: [general, openfn_code_quality]
---

# notes

User was on a workflow editor discussing workflow structure, then navigated to a job editor and asked an abrupt question about the current code. The model should recognise the navigation (via meta.last_page) and respond about the job code, not continue talking about workflow structure.

# quality_criteria

- The response is about the current job code (the patient mapping), not about workflow structure.
- The suggested_code includes a log statement at the start of the job body (e.g. `console.log(...)`).

# settings

## context.expression

```js
fn(state => {
  const patients = state.data.map(patient => ({
    id: patient.patient_id,
    name: patient.full_name,
    dob: patient.date_of_birth
  }));

  return { ...state, patients };
});

post('https://destination.api/patients', state => state.patients);
```

## context.adaptor

@openfn/language-common@latest

## context.page_name

map-patient-data

## meta.last_page

```json
{
  "type": "workflow",
  "name": "patient-sync"
}
```

## suggest_code

true

# history

## turn

### role

user

### content

[pg:workflow/patient-sync] Create a workflow to sync patient data from source to destination

## turn

### role

assistant

### content

I'll create a workflow with jobs to fetch patient data, transform it, and sync to the destination system.

## turn

### role

user

### content

[pg:workflow/patient-sync] Add validation between fetch and transform

## turn

### role

assistant

### content

I'll add a validation job that checks the patient data before transformation.

# turn

## role

user

## content

Add a log statement at the start
