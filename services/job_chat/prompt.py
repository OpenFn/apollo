from util import createLogger, apollo

logger = createLogger("job_chat.prompt")

system_message = """
You are an agent helping a non-export user write a job for OpenFn,
the world's leading digital public good for workflow automation.
You should STRICTLY ONLY answer questions related to OpenFn,
javascript programming, and workflow automation. Your responses
short be short, accurate and friendly unless otherwise instructed.
"""

# for now we're hard coding a sort of job writing 101 with code examples
# Later we'll do some real RAG against the docsite
job_writing_summary = """
Here is a guide to job writing in OpenFn.

A Job is written in a DSL which is very similar to Javascript.

Job code does not use import statements or async/await.

Job code must only contain function calls at the top level.

Each job is associated with an adaptor, which provides functions for the job.
All jobs have the fn() and each() function, which are very important.

DO NOT use the `alterState()` function. Use `fn()` instead.

The adaptor API may be attached.

The functions provided by an adaptor are called Operations. 

An Operation is a factory function which returns a function that takes state and returns state, like this:
```
const myOperation = (arg) => (state) => { /* do something with arg and state */ return state; }
```
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
</example>
<example>
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
<examples>
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

    message.append("<job_writing_guide>{}</job_writing_guide>".format(job_writing_summary))

    if context.has("adaptor"):
        message.append(
            "<adaptor>I am using the OpenFn {} adaptor, use functions provided by its API".format(context.adaptor)
        )

        adaptor_docs = apollo("describe_adaptor", {"adaptor": context.adaptor})
        for doc in adaptor_docs:
            message.append("Typescript definitions for doc")
            message.append(adaptor_docs[doc]["description"])
        message.append("</adaptor>")

    else:
        message.append("I am using an OpenFn Adaptor to write my job.")

    if context.has("expression"):
        message.append(
            "My code currently looks like this :```{}```\n\n You should try and re-use any relevant user code in your response".format(
                context.expression
            )
        )

    if context.has("input"):
        "<input>My input data is :\n\n```{}```</input>".format(context.input)

    if context.has("output"):
        "<output>My last output data was :\n\n```{}```</output>".format(context.output)

    if context.has("log"):
        "<log>My last log output was :\n\n```{}```</output>".format(context.log)

    return {"role": "user", "content": "\n\n".join(message)}


def build_prompt(content, history, context):
    prompt = []

    # push the history
    prompt.extend(history)

    # Add the question and context
    prompt.append(build_context(context, content))

    return (system_message, prompt)
