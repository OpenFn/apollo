Input 1:
Generated Job Expression:
```javascript
fn(state => {
  const visits = state.data; // Assuming state.data is an array of visit events

  const visitsWithIHS = visits.filter(visit => visit.ihs_number); // Filter visits with IHS number
  const visitsWithoutIHS = visits.filter(visit => !visit.ihs_number); // Filter visits without IHS number

  state.data = {
    visitsWithIHS,
    visitsWithoutIHS
  };

  return state;
});
```

==================================================

Input 2:
Generated Job Expression:
```javascript
each("$.data[*]",
  fn(state => {
    const fridgeId = state.data.LSER; // Assuming LSER is the attribute ID for fridge id
    const temperatures = state.data.records.map(record => record.TVC);
    
    state.data = {
      fridgeId,
      temperatures
    };
    
    return state;
  }),
  each("$.data[*].temperatures",
    fn(state => {
      const key = `${state.data.fridgeId}:${state.data.ADOP}`;
      const value = state.data;
      
      return set(key, value);
    })
  )
)
```

==================================================

Input 3:
Generated Job Expression:
```javascript
create('trackedEntityInstances', {
  orgUnit: 'dWOAzMcK2Wt',
  trackedEntityType: 'nEenWmSyUEp',
  attributes: [
    {
      attribute: 'NAME_ATTRIBUTE_ID', // Replace with the actual attribute ID for name
      value: state.data.name
    },
    {
      attribute: 'GENDER_ATTRIBUTE_ID', // Replace with the actual attribute ID for gender
      value: state.data.gender
    }
  ]
});
```

==================================================

