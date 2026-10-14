---
id: examples
order: 40
---
<examples>
<example>
Here's how we issue a GET request with the http adaptor:
```
get('/patients');
```
The first argument to get is the path to request from (the configuration will tell
the adaptor what base url to use). In this case we're passing a static string,
but we can also pass a value from state:
```
get(state => state.endpoint);
```
</example>
<example>
Example job code with the HTTP adaptor:
```
get('/patients');
fn(state => {
  const patients = state.data.map(p => {
    return { ...p, enrolled: true }
  });

  return { ...state, data: { patients } };
})
post('/patients', dataValue('patients'));
```
</example>
<example>
Example job code with the Salesforce adaptor:
```
each(
  '$.form.participants[*]',
  upsert('Person__c', 'Participant_PID__c', state => ({
    Participant_PID__c: state.pid,
    First_Name__c: state.participant_first_name,
    Surname__c: state.participant_surname,
  }))
);
```
</example>
<example>
Example job code with the ODK adaptor:
```
create(
  'ODK_Submission__c',
  fields(
    field('Site_School_ID_Number__c', dataValue('school')),
    field('Date_Completed__c', dataValue('date')),
    field('comments__c', dataValue('comments')),
    field('ODK_Key__c', dataValue('*meta-instance-id*'))
  )
);
```
</example>
</examples>
</job writing guide>
