from util import createLogger, apollo

logger = createLogger("job_chat.prompt")

# RAG
# Retrieval Augmented Generation
system_message = """
You are an agent helping a non-export user write a job for OpenFn,
the worlds leading digital public good for workflow automation.
You are helping the user write a job in OpenFn's custom dsl, which
is very similar to JAVASCRIPT. You should STRICTLY ONLY answer
questions related to OpenFn, javascript programming, and workflow automation.
"""

# for now we're hard coding a sort of job writing 101 with code examples
# Later we'll do some real RAG against the docsite
job_writing_summary = """
Here is a guide to job writing in OpenFn.

A Job is written in OpenFn DSL code to performs a particular task, like
fetching data from Salesforce or converting JSON data to FHIR standard.

Each job uses exactly one Adaptor to perform its task. The Adaptor provides a
collection of Operations (helper functions) which makes it easy to communicate with
a data source. The adaptor API for this job is provided below.

A job MUST NOT include an import or require statement.

A job MUST NOT use the execute() function.

A job MUST only contain function calls at the top level.

A job MUST NOT include any other JavaScript statements at the top level.

A job MUST NOT include assignments at the top level

A job SHOULD NOT use async/await or promises.

A job SHOULD NOT use `alterState`, instead it should use `fn` for data transformation.

An Operation is a factory function which returns a function that takes state and returns state, like this:
```
const myOperation = (arg) => (state) => { /* do something with arg and state */ return state; }
```
For example, here's how we issue a GET request with the http adaptor:
```
get('/patients');
```
The first argument to get is the path to request from (the configuration will tell
the adaptor what base url to use). In this case we're passing a static string,
but we can also pass a value from state:
```
get(state => state.endpoint);
```

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
"""


def build_context(context, question):
    message = []

    message.append(
        """Please help answer this question.
        <question>
        {}
        </question>

        Additional context is provided below:

        """.format(
            question
        )
    )

    # message.append("<job_writing_guide>{}</job_writing_guide>".format(job_writing_summary))

    # if context.has("adaptor"):
    #     message.append(
    #         "<adaptor>I am using the OpenFn {} adaptor, use functions provided by its API".format(context.adaptor)
    #     )

    #     adaptor_docs = apollo("describe_adaptor", {"adaptor": context.adaptor})
    #     for doc in adaptor_docs:
    #         message.append("Typescript definitions for doc")
    #         message.append(adaptor_docs[doc]["description"])
    #     message.append("</adaptor>")

    # else:
    #     message.append("I am using an OpenFn Adaptor to write my job.")

    if context.has("expression"):
        message.append(
            "My code currently looks like this :```{}```\n\n You should try and re-use any relevant user code in your response".format(
                context.expression
            )
        )

    if context.has("input"):
        "<input>My input data is :\n\n```{}```</input>".format(context.input)

    if context.has("output"):
        "<output>My last output data was :\n\n```{}```<output>".format(context.output)

    if context.has("log"):
        "<log>My last log output was :\n\n```{}```".format(context.log)

    return {"role": "user", "content": "\n\n".join(message)}


def build_prompt(content, history, context):
    prompt = []

    # push the history
    prompt.extend(history)

    # Add the question and context
    prompt.append(build_context(context, content))

    return (system_message, prompt)
