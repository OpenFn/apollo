## Input 1:
### Instruction: 
Create a job which filters an array of Commcare visit events. The visits will be passed downstream in state.data. Sort the events into two lists of patients: those with an IHS number (defined by the key 'ihs_number', and those without. Save the two arrays to state, remove any other data, and return the state for the next job.

## Generated Job Expression:
```javascript
fn(state => {
  // Filter the array of Commcare visit events into two lists based on the presence of an IHS number
  const visitsWithIHS = state.data.filter(event => event.ihs_number);
  const visitsWithoutIHS = state.data.filter(event => !event.ihs_number);

  // Save the two arrays to state and remove any other data
  state.visitsWithIHS = visitsWithIHS;
  state.visitsWithoutIHS = visitsWithoutIHS;
  state.data = null; // Remove any other data

  return state; // Return the state for the next job
});
```

==================================================

## Input 2:
### Instruction: 
Given a payload of metadata about fridge operating temperatures, aggregate all the records belonging to each fridge. The fridge id is in the LSER field.  There may be hundreds of items in the data, with dozens of records per item. Save the list of temperatures (TVC) for each fridge in an object on state, like `{ records:  { '406c9f14667442a7924fbe6ac8b98185': [6.9, 6.9, 7.0] } }`. Once the data has been aggregated, upload it to redis using the fridge id and date (ADOP) as the key, like '<fridge-id>:<ADOP>'

## Generated Job Expression:
```javascript
each("$.data",
  fn(state => {
    const fridgeId = state.data.LSER;
    const temperatures = state.data.records.map(record => record.TVC);
    
    state.temperatures ??= {};
    state.temperatures[fridgeId] ??= [];
    state.temperatures[fridgeId].push(...temperatures);
    
    return state;
  })
);

each("$.temperatures",
  fn(state => {
    const fridgeId = state.data.key;
    const temperatures = state.data.value;
    const key = `${fridgeId}:${state.data.ADOB}`;
    
    return hset(key, temperatures);
  })
);
```

==================================================

## Input 3:
### Instruction: 
Create a new trackedEntityInstance 'person' in dhis2 for the 'dWOAzMcK2Wt' orgUnit.

## Generated Job Expression:
```javascript
create('trackedEntityInstances', {
  orgUnit: 'dWOAzMcK2Wt',
  trackedEntityType: 'YOUR_TRACKED_ENTITY_TYPE_ID', // Replace with the correct tracked entity type ID
  attributes: [
    {
      attribute: 'YOUR_ATTRIBUTE_ID_FOR_NAME', // Replace with the correct attribute ID for name
      value: state.data.name
    },
    {
      attribute: 'YOUR_ATTRIBUTE_ID_FOR_GENDER', // Replace with the correct attribute ID for gender
      value: state.data.gender
    }
  ]
});
```

==================================================

