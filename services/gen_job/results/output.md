Input 1:
Generated Job Expression:
```javascript
fn(state => {
  const { data } = state;
  const visits = data.visits || [];
  
  const visitsWithIHS = visits.filter(visit => visit.ihs_number);
  const visitsWithoutIHS = visits.filter(visit => !visit.ihs_number);
  
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
```js
each("$.data",
  fn(state => {
    const fridgeId = state.data.LSER;
    const temperatures = state.data.records.map(record => record.TVC);
    state.data = { fridgeId, temperatures };
    return state;
  }),
  each("$.data",
    jSet(`${state.data.LSER}:${state.data.ADOP}`, state.data.temperatures)
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
      attribute: 'ATTRIBUTE_ID_FOR_NAME', // Add the correct attribute ID for name
      value: state.data.name
    },
    {
      attribute: 'ATTRIBUTE_ID_FOR_GENDER', // Add the correct attribute ID for gender
      value: state.data.gender
    }
  ]
});
```
==================================================

