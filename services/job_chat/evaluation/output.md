# what is state

State is a JavaScript object passed through each operation in your workflow. It
has two main properties:

1. `data` - Contains the current data you're working with
2. `references` - An array containing the history of all previous operations

Each operation in your workflow:

1. Receives the current state
2. Does something with it
3. Returns a modified state to the next operation

In your current job, you're using `fn(s => s)` which simply receives the state
object and returns it unchanged.

If you want to see what's in your state, try:

```js
fn((state) => {
  console.log(state);
  return state;
});
```

### RAG

## job-writing-guidejavascript

# what does $ mean

The `$` symbol is a shorthand in OpenFn for accessing values from your state
object.

It's essentially syntactic sugar for `(state) => state`, allowing you to access
data without having to explicitly write state handling functions.

Instead of writing:

```js
get((state) => state.data.url);
```

You can simply write:

```js
get($.data.url);
```

The `$` operator is resolved at the correct time by the OpenFn runtime. You can
use it to read from state in function arguments, but you can't use it for direct
assignments.

### RAG

## troubleshootingcli-walkthroughjob-writing-guide

# How do I download all items from a collection from a particular day? Like 29th march 2024? See my input for an example of what my keys look like

You can use the collections adaptor to query items with pattern matching and
date filtering. Here's how to get all items from March 29th, 2024:

```js
collections.get("my-collection", "20240329*").then((state) => {
  state.marchItems = state.data;
  return state;
});
```

This uses a pattern match to find all keys that start with "20240329" (which are
your March 29th items based on your key format).

Alternatively, you can also filter by creation date:

```js
collections
  .get("my-collection", {
    createdAfter: "20240329",
    createdBefore: "20240330",
  })
  .then((state) => {
    state.marchItems = state.data;
    return state;
  });
```

For more information on collections, refer to the official documentation here:
https://docs.openfn.org/adaptors/packages/collections-docs.

### RAG

## salesforcesurveyctojob-writing-guidecollections

# can you fill out this code for me?

Here's a complete implementation of your code that creates a FHIR patient and
adds it to a bundle:

```js
fn((state) => {
  const input = state.data; // take the input from state.data

  // create a basic FHIR patient
  state.patient = {
    resourceType: "Patient",
    id: "example-patient-id",
    active: true,
    name: [
      {
        use: "official",
        family: "Smith",
        given: ["John"],
      },
    ],
    gender: "male",
    birthDate: "1970-01-01",
  };

  return state;
});

fn((state) => {
  // create a new FHIR bundle
  state.bundle = {
    resourceType: "Bundle",
    type: "transaction",
    entry: [
      {
        resource: state.patient,
        request: {
          method: "PUT",
          url: `Patient/${state.patient.id}`,
        },
      },
    ],
  };

  return state;
});

// Optional: post the bundle to Satusehat
// post('', state.bundle);
```

This code:

1. Creates a patient with basic FHIR-compliant fields
2. Creates a bundle with the patient as an entry
3. Sets up the bundle as a transaction type with a PUT request

You can customize the patient data fields and add more resources to the bundle
as needed.

### RAG

## satusehatfhir-4

# What is wrong with this code? I get an error like "Cannot read properties of undefined (reading 'name')"

There's a syntax error in your code. You're missing a semicolon after the
console.log statement. Here's the corrected version:

```js
fn((state) => {
  state.patient = state.data.patients[0];
  return state;
});
fn((state) => {
  console.log(state.patient.name);
  return state;
});
```

Always remember to return state from your fn() operations and check that your
JavaScript syntax is correct with proper semicolons.

Also, your error suggests that `state.patient.name` is undefined. Make sure your
input data actually contains `patients` array with at least one item that has a
`name` property.

### RAG

## claudejavascriptlibrary-introdhis2job-writing-guidecommonocl

# What is wrong with this code? I get an error like "fn is not defined"

Your code is missing the `fn` function wrapper. In OpenFn jobs, you need to use
the `fn()` operation to run JavaScript code that manipulates the state.

Try this instead:

```js
fn((state) => {
  console.log(state.data);
  return state;
});
```

This properly wraps your `console.log` statement in the `fn()` operation, which
is provided by the common adaptor.

### RAG

## troubleshootingdhis2commoncli-walkthroughjavascriptlibrary-introclaudeocl

# Why does the http result not get written to my state?

Your code is calling `http.get()`, but you're not capturing the result. Also,
you need to use the exported function directly rather than nesting it inside
`fn()`.

Try this instead:

```js
get("https://jsonplaceholder.typicode.com/todos/1");
```

Or if you want to use the http module specifically:

```js
http.get("https://jsonplaceholder.typicode.com/todos/1");
```

Both will update `state.data` with the response from the API.

### RAG

## statedhis2library-introcli-walkthroughoclcommonclaudejob-writing-guide

# would you please write a job for me that creates new datavaluesets under the "Approved School CHP" organization unit

I can write a job to create a dataValueSet for the "Approved School CHP"
organization unit. This would typically involve specifying the organization unit
ID, a dataSet ID, period, and the data values to submit.

Here's a basic implementation:

```javascript
create("dataValueSets", {
  dataSet: "DATASET_ID", // Replace with your actual dataSet ID
  period: "202401", // Format: YYYYMM (January 2024 in this example)
  orgUnit: "ORGUNIT_ID", // Replace with the ID for "Approved School CHP"
  dataValues: [
    {
      dataElement: "DATA_ELEMENT_ID_1", // Replace with your actual data element ID
      value: "10", // The value to submit
      categoryOptionCombo: "CATEGORY_OPTION_COMBO_ID", // Optional, if needed
    },
    // Add more data values as needed
    {
      dataElement: "DATA_ELEMENT_ID_2",
      value: "20",
    },
  ],
});
```

To use this job, you'll need to replace:

1. `DATASET_ID` with your actual dataSet ID
2. `ORGUNIT_ID` with the ID for "Approved School CHP"
3. `DATA_ELEMENT_ID_1`, `DATA_ELEMENT_ID_2`, etc. with your actual data element
   IDs
4. `CATEGORY_OPTION_COMBO_ID` with your category option combo ID (if needed)

You'll need to know these IDs from your DHIS2 system. You can find them by using
the "get" operation first to query your DHIS2 system for the relevant
information.

### RAG

## dhis2kobo-to-dhis2

# What do I do now?

You've created a basic job using the common adaptor that simply returns the
current state. This is a good starting point.

To build a useful job, you need to decide what you want to achieve:

1. If you want to transform data, use the `fn()` function to manipulate state
2. If you need to process multiple records, use `each()` to iterate through
   items
3. If you need to make HTTP requests, add operations like `get()` or `post()`

Here's a simple example that transforms data:

```js
fn((state) => {
  // Extract data you need
  const data = state.data;

  // Transform it
  const transformed = {
    ...data,
    processed: true,
    timestamp: new Date().toISOString(),
  };

  // Return updated state
  return { ...state, data: transformed };
});
```

What are you trying to accomplish with this job?

### RAG

## claudelibrary-introbuild-compliant-appsocldhis2commoncli-walkthrough

# Can you write a cron code that will trigger at 1am India time?

In OpenFn, you don't write cron code directly in job scripts. Triggers are
configured separately in the platform interface.

To trigger a job at 1am India time (UTC+5:30), you would set up a time trigger
in the OpenFn interface with:

```
30 19 * * *
```

This is standard cron format representing 19:30 UTC, which is 1:00am in India
time.

When setting up the trigger in the OpenFn platform, you'll select "Timer" as the
trigger type, then enter this cron expression.

### RAG

---

# Who can see these messages?

Only users who have access to this job in the workflow can see these chat
messages. Chat sessions are saved to each job, so anyone with permission to view
the workflow will see our conversation.

### RAG

---

# What is fhir and how do I use it?

FHIR (Fast Healthcare Interoperability Resources) is a standard for representing
and exchanging healthcare data electronically. It's designed to facilitate
interoperability between different healthcare systems.

OpenFn provides multiple FHIR-related adaptors:

- `fhir` - A generic adaptor for basic FHIR operations
- `fhir-r4` - Specifically for FHIR Release 4
- `fhir-fr` - A custom adaptor for the France FHIR Implementation Guide
- `fhir-ndr-et` - A custom adaptor for Ethiopia's HIV Treatment & Care Services

To use FHIR with OpenFn, you'd need to:

1. Install the appropriate FHIR adaptor for your needs
2. Set up credentials to connect to your FHIR server
3. Use the adaptor's operations to interact with FHIR resources

FHIR can be integrated via:

- REST API for scheduled or bulk synchronizations
- Webhooks/subscriptions for real-time event-based integration

For more information and detailed documentation, visit:

- https://docs.openfn.org/adaptors/fhir
- https://www.hl7.org/fhir/overview.html

### RAG

## fhir-ndr-etfhir-frfhirfhir-4

# How can I generate a UUID for my data?

To generate a UUID in your job, use the `util.uuid()` function:

```js
fn((state) => {
  const id = util.uuid();
  console.log(id); // Example: '3f4e254e-8f6f-4f8b-9651-1c1c262cc83f'

  // Add the UUID to your data if needed
  return { ...state, data: { ...state.data, id } };
});
```

This will create a standard UUID and add it to your data under the `id` field.
You can modify the property name as needed.

### RAG

## oclclaudelibrary-introhttpdhis2commoncli-walkthroughportability-versions

# I want to download data from a file on sharepoint and upload leads into salesforce. Can you give me an idea how that would work?

This is a common integration scenario. You'll need a workflow with multiple
steps:

1. First step - Use the MSGraph adaptor to download the file from SharePoint
2. Second step - Process the file data (transform it into the format needed for
   Salesforce)
3. Third step - Upload the transformed data to Salesforce as leads

Here's a rough outline of how the job code would look:

**Step 1: Download from SharePoint (using MSGraph adaptor)**

```js
http.get("/sites/{site-id}/drive/items/{file-id}/content");
```

**Step 2: Transform data (using Common adaptor)**

```js
fn((state) => {
  // Parse the file content (if it's CSV/Excel)
  // Transform the data into Salesforce format
  const leads = state.data.map((row) => ({
    LastName: row.name,
    Company: row.company,
    Email: row.email,
    // Map other fields as needed
  }));

  return { ...state, leads };
});
```

**Step 3: Upload to Salesforce (current adaptor)**

```js
bulk("Lead", "insert", (state) => state.leads, { failOnError: true });
```

You'll need to set up credentials for both MSGraph and Salesforce in your
project. The exact SharePoint URL details will depend on your specific
SharePoint structure.

### RAG

## googlesheetsopensppdynamicssalesforceodoomsgraphopenmrssftpmssql

# I want to search for all patients with the name on state.name, and for each one, update their location to the value on state.newLocation

I'll help you search for patients by name and update their location. Here's how
you can do it:

```js
fn((state) => {
  // Extract the name and new location from state
  const name = state.name;
  const newLocation = state.newLocation;

  if (!name || !newLocation) {
    throw new Error("Missing required data: name or newLocation");
  }

  return { ...state, name, newLocation };
}),
  // Search for patients with the given name
  searchPatient({ q: (state) => state.name }),
  // Process each patient found in the search results
  fn((state) => {
    // Log how many patients were found
    console.log(
      `Found ${state.data.results.length} patients matching the name`
    );

    // Return the patients in state for the next operation
    return { ...state, patients: state.data.results };
  }),
  // For each patient, update their location
  each(
    "patients[*]",
    update(
      "person",
      (state) => state.uuid,
      (state) => ({
        // Include any required fields for person update
        uuid: state.uuid,
        address: {
          location: state.newLocation,
        },
      })
    )
  );
```

This job will:

1. First extract and validate the name and newLocation from state
2. Search for patients with the given name
3. Log how many matching patients were found
4. For each patient in the results, update their location

Note: The exact structure for the location update may need adjustments based on
the specific OpenMRS implementation and data model you're working with. The
field names (`address.location`) might be different in your system.

### RAG

godatacommcare-to-dbopenlmisapi-discoveryopenmrsopenimisactivity-history
