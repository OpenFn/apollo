## question

what is state

## adaptor

@openfn/language-salesforce@4.6.10

## code

fn(s => s)

## input

{}

---

## adaptor

@openfn/language-salesforce@6.0.0

## code

get($.data.url)

## question

what does $ mean

## input

{}

---

## question

How do I download all items from a collection from a particular day? Like 29th
march 2024? See my input for an example of what my keys look like

## adaptor

@openfn/language-salesforce@6.0.0

## code

get($.data.url)

## input

{ "data": [{ "key": "20240102-5901257", "name": "Tom Waits", "id": "5901257", },
{ "key": "20240213-0183216", "name": "Billie Holiday", "id": "0183216", }] }

---

## question

How do I add my input data to a collection? Use the date and id for the key

## adaptor

@openfn/language-openmrs@6.4.0

## code

get($.data.url)

## input

{ "data": [{ "date": "5901257", "name": "Tom Waits", "id": "5901257", }, {
"date": "20240213", "name": "Billie Holiday", "id": "0183216", }] }

---

## question

can you fill out this code for me?

## adaptor

@openfn/language-satusehat@2.0.10

## code

fn(state => {
  const input = state.data;
// take the input from state.data and create a fhir patient
state.patient = {}
return state;
});

fn(state => {
  // create a new fhir bundle

  // add the patient to it
})

---

## question

What is wrong with this code? I get an error like "Cannot read properties of
undefined (reading 'name')"

## adaptor

@openfn/language-common@2.0.0

## code

fn(state => { state.patient = state.data.patients[0]; });

fn(state => { console.log(state.patient.name) return state; })

---

## question

What is wrong with this code? I get an error like "fn is not defined"

## adaptor

@openfn/language-common@2.0.0

## code

console.log(state.data)

---

## question

Why does the http result not get written to my state?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => {
  http.get('https://jsonplaceholder.typicode.com/todos/1')
  return s;
})

---

## question

would you please write a job for me that creates new datavaluesets under the
"Approved School CHP" organization unit

## adaptor

@openfn/language-dhis2@6.3.1

## code

fn(s => s)

---

## question

What do I do now?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => s)

---

## question

Can you write a cron code that will trigger at 1am India time?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => s)

---

## question

Who can see these messages?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => s)

---

## question

What is fhir and how do I use it?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => s)

---

## question

How can I generate a UUID for my data?

## adaptor

@openfn/language-common@2.0.0

## code

fn(s => s)

---

## question

I want to download data from a file on sharepoint and upload leads into
salesforce. Can you give me an idea how that would work?

## adaptor

@openfn/language-salesforce@6.0.0

## code

fn(s => s)


--

## question

I want to search for all patients with the name on state.name, and for each one, update their location to the value on state.newLocation

## adaptor

@openfn/language-openmrs@4.4.0

## code

fn(state => {
  return state
});

