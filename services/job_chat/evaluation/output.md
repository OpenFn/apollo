# what is state
In OpenFn, `state` is the core data object that flows through your workflow. It contains:

- `state.data` - The main data payload (usually from your input or previous operations)
- `state.references` - Array of results from previous operations in the workflow
- `state.configuration` - Your credential/connection settings (handled securely by OpenFn)

You can access and modify state in your job code:

```js
fn(state => {
  console.log(state.data); // Your input data
  console.log(state.references); // Previous operation results
  
  // Modify state
  state.data.newField = 'hello';
  
  return state; // Always return state
});
```

State is passed between each operation in your job, allowing data to flow through your workflow pipeline.

### RAG
standards,javascript,job-writing-guide
---
# what does $ mean
In OpenFn job code, `$` is the **lazy state operator**. It's a shorthand way to reference data from the state object.

Instead of writing `state.data.something`, you can use `$.data.something`. The `$` ensures the value is resolved at the correct time during job execution.

Examples:
```js
// These are equivalent:
get($.data.url)
get(state => state.data.url)

// Access nested data:
get($.patient.id)

// Use in string templates:
get(`/patients/${$.patient.id}`)

// Use in operations:
create('Account', {
  name: $.customer.name,
  email: $.customer.email
})
```

Key points:
- `$` can only be used to **read** from state, not assign to it
- It can only be used inside function arguments (like operation parameters)
- It's syntactic sugar that gets converted to `state => state` during compilation

Think of `$` as a path pointing to your state data that gets resolved automatically at runtime.

### RAG
job-writing-guide,troubleshooting,library-intro
---
# How do I download all items from a collection from a particular day? Like 29th march 2024? See my input for an example of what my keys look like
Looking at your data structure where keys are in format `YYYYMMDD-ID`, you can fetch all items from March 29th, 2024 using the Collections adaptor with a pattern filter:

```js
collections.get('my-collection', '20240329*');
```

This will download all items where the key starts with `20240329` (March 29th, 2024).

If you need to process each item individually instead of loading them all at once, use `each()`:

```js
collections.each('my-collection', '20240329*', (state, value, key) => {
  console.log(`Processing ${key}:`, value);
  // Process each item here
  return state;
});
```

The `*` wildcard matches any characters after the date, so it will capture all records from that specific day regardless of the ID portion.

### RAG
collections,surveycto,salesforce,job-writing-guide
---
# How do I add my input data to a collection? Use the date and id for the key
To add your input data to a collection using the date and id for the key, use this code:

```js
collections.set('my-collection', item => `${item.date}-${item.id}`, $.data);
```

This will:
- Store each item from your input data array
- Generate keys like `5901257-5901257` and `20240213-0183216`
- Use the date and id properties from each item to create the key

### RAG
openlmis,collections,openmrs,openimis
---
# can you fill out this code for me?
Here's the completed code to create a FHIR patient and add it to a bundle:

```js
fn(state => {
  const input = state.data;
  
  // Create a FHIR patient resource
  state.patient = {
    resourceType: 'Patient',
    id: 'patient-001', // You may want to generate this dynamically
    identifier: [
      {
        system: 'https://fhir.kemkes.go.id/id/nik',
        value: input.nik || 'default-nik'
      }
    ],
    name: [
      {
        use: 'official',
        family: input.lastName || 'Unknown',
        given: [input.firstName || 'Unknown']
      }
    ],
    gender: input.gender || 'unknown',
    birthDate: input.birthDate || null,
    active: true
  };
  
  return state;
});

fn(state => {
  // Create a new FHIR bundle
  state.bundle = {
    resourceType: 'Bundle',
    type: 'collection',
    entry: []
  };
  
  // Add the patient to the bundle
  state.bundle.entry.push({
    resource: state.patient,
    request: {
      method: 'POST',
      url: 'Patient'
    }
  });
  
  return state;
});
```

This code:
1. Creates a FHIR Patient resource using data from `state.data`
2. Creates a FHIR Bundle
3. Adds the patient to the bundle as an entry

You'll need to adjust the field mappings based on your actual input data structure.

### RAG
satusehat,fhir-4
---
# What is wrong with this code? I get an error like "Cannot read properties of undefined (reading 'name')"
The error occurs because `state.data.patients` is undefined or empty. In the first `fn()`, you're trying to access `state.data.patients[0]`, but since your input data is an empty object `{}`, there's no `patients` array.

Add a safety check:

```js
fn(state => { 
  state.patient = state.data.patients?.[0]; 
  return state;
});

fn(state => { 
  if (state.patient?.name) {
    console.log(state.patient.name);
  }
  return state; 
});
```

Also note that you forgot to return `state` in your first function - always return state from `fn()`.

### RAG
dhis2,job-writing-guide,library-intro,common,ocl,javascript,claude
---
# What is wrong with this code? I get an error like "fn is not defined"
The issue is that you're missing the `fn()` wrapper. In OpenFn, you can't just write bare JavaScript code - you need to wrap it in an `fn()` operation.

Change your code to:

```js
fn(state => {
  console.log(state.data);
  return state;
});
```

The `fn()` function is required to execute custom JavaScript in OpenFn jobs. It takes a function that receives the current state and must return the state (potentially modified).

### RAG
ocl,claude,library-intro,javascript,common,cli-walkthrough,portability,dhis2
---
# Why does the http result not get written to my state?
Your HTTP request isn't getting written to state because you're not returning the result of the `http.get()` call. In your current code:

```js
fn(s => { 
  http.get('https://jsonplaceholder.typicode.com/todos/1') 
  return s; 
})
```

You're calling `http.get()` but not doing anything with its result, and you're returning the original state `s`.

To fix this, you have two options:

**Option 1: Use `http.get()` directly (recommended)**
```js
http.get('https://jsonplaceholder.typicode.com/todos/1')
```

**Option 2: If you need to use it inside `fn()`, return the operation**
```js
fn(s => http.get('https://jsonplaceholder.typicode.com/todos/1')(s))
```

The first option is simpler and follows OpenFn best practices. The `http.get()` operation will automatically write the response to `state.data` and include the full response details in `state.response`.

### RAG
state,dhis2,library-intro,common,claude,cli-walkthrough,job-writing-guide,ghana-bdr,ocl
---
# would you please write a job for me that creates new datavaluesets under the "Approved School CHP" organization unit
Here's a job that creates new dataValueSets under the "Approved School CHP" organization unit:

```javascript
create('dataValueSets', {
  orgUnit: 'Approved School CHP', // You may need to use the orgUnit ID instead
  dataSet: 'YOUR_DATASET_ID', // Replace with your actual dataset ID
  period: '202412', // Replace with your desired period (e.g., 202412 for Dec 2024)
  completeDate: '2024-12-01', // Optional completion date
  dataValues: [
    {
      dataElement: 'YOUR_DATA_ELEMENT_ID', // Replace with actual data element ID
      value: '10'
    },
    {
      dataElement: 'ANOTHER_DATA_ELEMENT_ID', // Replace with another data element ID  
      value: '25'
    }
  ]
});
```

You'll need to replace:
- `YOUR_DATASET_ID` with the actual dataset ID
- `YOUR_DATA_ELEMENT_ID` with the actual data element IDs you want to report
- The period format (e.g., `202412` for monthly, `2024` for yearly)
- The values with your actual data

Note: You might need to use the organization unit ID instead of the name. If "Approved School CHP" doesn't work, find the orgUnit ID from your DHIS2 instance.

### RAG
dhis2,kobo-to-dhis2
---
# What do I do now?
Your job currently just has `fn(s => s)` which passes state through unchanged.

To do something useful, you need to:

1. **Add some input data** - Go to the Input tab and add some JSON data to work with
2. **Write job logic** - Replace `fn(s => s)` with operations that transform your data

Here are some examples of what you could do:

**Transform data:**
```js
fn(state => {
  const transformedData = state.data.map(item => ({
    ...item,
    processed: true
  }));
  
  return { ...state, data: transformedData };
});
```

**Make HTTP requests:**
```js
http.get('https://jsonplaceholder.typicode.com/posts');
```

**Process arrays:**
```js
each('$.data[*]', fn(state => {
  console.log('Processing item:', state.data);
  return state;
}));
```

What kind of data processing or integration are you trying to accomplish?

### RAG
cli-walkthrough,ocl,library-intro,claude,common,dhis2,build-compliant-apps
---
# Can you write a cron code that will trigger at 1am India time?
Here's the cron expression for 1 AM India Standard Time (IST):

```
30 19 * * *
```

This translates to:
- **30** - 30 minutes
- **19** - 19th hour (7:30 PM UTC)
- **\*** - every day of the month
- **\*** - every month
- **\*** - every day of the week

Since India Standard Time is UTC+5:30, 1:00 AM IST equals 7:30 PM UTC (19:30 in 24-hour format).

Note: OpenFn cron jobs run on UTC time, so you need to convert your local time to UTC for the cron expression.

### RAG

---
# Who can see these messages?
Anyone who can see the workflow can see the chat. Chat sessions are saved to each job, so if someone has access to view the workflow, they'll be able to see our conversation here.

### RAG

---
# What is fhir and how do I use it?
FHIR (Fast Healthcare Interoperability Resources) is a standard for representing and exchanging healthcare data electronically. It's designed to enable interoperability between different healthcare systems.

## What is FHIR?

FHIR provides:
- Standardized data formats for healthcare information
- REST APIs for data exchange
- Resources like Patient, Observation, Medication, etc.
- Support for real-time and batch data integration

## Using FHIR with OpenFn

OpenFn offers several FHIR adaptors:

1. **Generic FHIR adaptor** (`@openfn/language-fhir`) - Basic, works with any FHIR server
2. **FHIR R4 adaptor** (`@openfn/language-fhir-4`) - Specifically for FHIR R4 with TypeScript support
3. **Custom Implementation Guide adaptors** - Generated for specific FHIR implementations

## Integration Options

**REST API Integration:**
- Pull data from FHIR servers
- Push data to FHIR servers
- Suitable for scheduled bulk syncs

**Webhook Integration:**
- Real-time, event-based data integration
- Uses FHIR Subscription resources
- Implementation varies by FHIR server

## Getting Started

To use FHIR in your workflow:

1. Choose the appropriate FHIR adaptor for your version
2. Set up credentials for your FHIR server
3. Use the adaptor's functions to interact with FHIR resources

Would you like help setting up a specific FHIR integration or working with particular FHIR resources?

### RAG
fhir-fr,fhir-ndr-et,fhir-4,fhir
---
# How can I generate a UUID for my data?
You can generate a UUID using the `util.uuid()` function from the common adaptor:

```js
fn(state => {
  const id = util.uuid();
  console.log('Generated UUID:', id);
  
  // Add the UUID to your data
  return {
    ...state,
    data: {
      ...state.data,
      id: id
    }
  };
});
```

The `util.uuid()` function generates a standard UUID (Universally Unique Identifier) that looks like: `'3f4e254e-8f6f-4f8b-9651-1c1c262cc83f'`

### RAG
claude,http,portability-versions,library-intro,dhis2,ocl,common,cli-walkthrough
---
# I want to download data from a file on sharepoint and upload leads into salesforce. Can you give me an idea how that would work?
Here's how you could set up a workflow to download data from SharePoint and upload leads to Salesforce:

## Workflow Structure

You'll need a 3-step workflow:

1. **Step 1**: Download file from SharePoint (using `http` adaptor)
2. **Step 2**: Transform/map the data (using `common` adaptor) 
3. **Step 3**: Upload leads to Salesforce (using `salesforce` adaptor)

## Step 1: Download from SharePoint
```js
// Assuming you have SharePoint API access
get('/sites/yoursite/lists/yourlist/items', {
  headers: {
    'Accept': 'application/json',
    'Authorization': 'Bearer your-token'
  }
});
```

## Step 2: Transform Data
```js
fn(state => {
  const leads = state.data.value.map(item => ({
    FirstName: item.fields.FirstName,
    LastName: item.fields.LastName,
    Email: item.fields.Email,
    Company: item.fields.Company,
    Status: 'Open - Not Contacted'
  }));
  
  return { ...state, leads };
});
```

## Step 3: Upload to Salesforce
```js
bulk('Lead', 'insert', $.leads, { 
  failOnError: true 
});
```

## Key Considerations

- **SharePoint Authentication**: You'll need to configure credentials for SharePoint API access
- **File Format**: If it's a CSV file, you might need to use `parseCsv()` in step 2
- **Data Mapping**: Map SharePoint fields to Salesforce Lead fields
- **Error Handling**: Use `failOnError: true` to catch any upload issues

Would you like me to elaborate on any of these steps or help with specific field mappings?

### RAG
salesforce,job-writing-guide,kobotoolbox,cli-walkthrough,magpi,steps,googlesheets,satusehat,standards,terminology
---
# I want to search for all patients with the name on state.name, and for each one, update their location to the value on state.newLocation
Here's the code to search for patients by name and update their location:

```js
searchPatient({ q: dataValue('name') });

each(
  '$.data.results[*]',
  update('patient', dataValue('uuid'), {
    person: {
      addresses: [{
        address1: sourceValue('$.newLocation'),
        preferred: true
      }]
    }
  })
);
```

This will:
1. Search for patients matching the name from `state.name`
2. For each patient found, update their address with the new location from `state.newLocation`

Note: The update requires the full person object structure. You may need to adjust the address fields based on your OpenMRS configuration and what address fields you want to update.

### RAG
openmrs,openlmis,mapping-specs,openimis,terminology