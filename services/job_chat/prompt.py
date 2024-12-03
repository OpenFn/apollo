from util import create_logger, apollo

logger = create_logger("job_chat.prompt")

system_role = """
You are a software engineer helping a non-expert user write a job for OpenFn,
the world's leading digital public good for workflow automation.

Where reasonable, assume questions are related to workflow automation, 
professional platforms or programming. You may provide general information around these topics, 
e.g. general programming assistance unrelated to job writing.
If a question is entirely irrelevant, do not answer it.

Your responses should be short, accurate and friendly unless otherwise instructed.

Do not thank the user or be obsequious.

Address the user directly.

Additional context is attached.
"""

job_writing_summary = """
An OpenFn Job is written in a DSL which is very similar to Javascript.

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

class Context:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    
    def has(self, key):
        return hasattr(self, key) and getattr(self, key) is not None

def generate_system_message(context_dict):
    # Convert dict to Context object if needed
    context = context_dict if isinstance(context_dict, Context) else Context(**context_dict)
    
    message = [system_role]

    message.append("<job_writing_guide>{}</job_writing_guide>".format(job_writing_summary))

    # Add a cache breakpoint after the job writing guide
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("adaptor"):
        adaptor_string = "<adaptor>The user is using the OpenFn {} adaptor. Use functions provided by its API.".format(
            context.adaptor
        )

        adaptor_docs = apollo("describe_adaptor", {"adaptor": context.adaptor})
        for doc in adaptor_docs:
            adaptor_string += "Typescript definitions for doc " + doc
            adaptor_string += adaptor_docs[doc]["description"]
        adaptor_string += "</adaptor>"

        message.append(adaptor_string)
    else:
        message.append("The user is using an OpenFn Adaptor to write the job.")

    # Add a cache breakpoint after the adaptor static stuff
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("expression"):
        message.append("<user_code>{}</user_code>".format(context.expression))

    if context.has("input"):
        message.append("<input>The user's input data is :\n\n```{}```</input>".format(context.input))

    if context.has("output"):
        message.append("<output>The user's last output data was :\n\n```{}```</output>".format(context.output))

    if context.has("log"):
        message.append("<log>The user's last log output was :\n\n```{}```</log>".format(context.log))

    return list(map(lambda text: text if isinstance(text, dict) else {"type": "text", "text": text}, message))

def build_prompt(content, history, context):
    system_message = generate_system_message(context)

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})

    return (system_message, prompt)