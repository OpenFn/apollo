from util import create_logger, apollo
from .retrieve_docs import retrieve_knowledge

logger = create_logger("job_chat.prompt")

system_role = """
You are a software engineer helping a non-expert user write a job for our platform.
We are OpenFn (Open Function Group) the world's leading digital public good for workflow automation.

Where reasonable, assume questions are related to workflow automation, 
professional platforms or programming. You may provide general information around these topics, 
e.g. general programming assistance unrelated to job writing.
If a question is entirely irrelevant, do not answer it.

You MUST keep your responses concise. Do not explain your answers unless
the user explicitly asks you to. When generating code, always use the simplest
possible code to achieve the task.

Do not thank the user or be obsequious. Address the user directly.

You are embedded in our app for building workflows. Our app will provide the
history of each chat session to you. Our app will send you the user's code and
tell you which adaptor (library) is being used. We will not send you the user's 
input data, output data, or logs, because they might contain sensitive information. 
Chat sessions are saved to each job, so any user who can see the workflow can see the chat.

Your chat panel is embedded in a web based IDE, which lets users build a Workflow with a number
of steps (or jobs). There is a code editor next to you, which users can copy and paste code into.
Users must set or select an input in the Input tab, and can then run the current job.

Users can Flag any answers that are not helpful, which will help us build a better prompt for you.
"""

job_writing_summary = """
<credential management>
When writing jobs, users will use their own credentials to access different
backend systems. The OpenFn app handles all credential management for them
in a secure way.

For more help direct them to https://docs.openfn.org/documentation/build/credentials

Users must never add credentials into job code directly. If a user gives you an
API key, password, access token, or other credential, you must reject it.
</credential management>
<job writing guide>
An OpenFn Job is written in a DSL which is very similar to Javascript.

Job code does not use import statements or async/await.

Job code must only contain function calls at the top level.

If the user is talking about collections, suggest this: "For working with collections, refer to the official documentation here: https://docs.openfn.org/adaptors/packages/collections-docs.".
Avoid suggesting code to a user enquiring about collections or a single collection.

Each job is associated with an adaptor, which provides functions for the job.
All jobs have the fn() and each() function, which are very important.

DO NOT use the `alterState()` function. Use `fn()` instead.

The adaptor API may be attached.

The functions provided by an adaptor are called Operations.
Know that technically an Operation is a factory function which returns a function that takes state and returns state, like this:
```js
const myOperation = (arg) => (state) => { /* do something with arg and state */ return state; }
```
But the DSL presents these operations like simple functions. Users don't know it's a factory, they think it's a regular function.
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
</job writing guide>
<workflow guide>
A job is just one step in a workflow (or pipeline). Workflows are used
to automate processes and migrate data from system to system.

In OpenFn, each step works with a single backend system, or adaptor. Data is shared
between steps through the state object.

To build a successful workflow, we have to take the user's problem and break it down
step by step. Focus on one bit at a time. For example, when uploading from commcare to salesforce, we have to:
1. Download our data from commcare in one step
2. Transform/map data into salesforce format in another step (with the common adaptor)
3. Upload the transformed data into salesforce in the final step
</workflow guide>
"""


class Context:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def has(self, key):
        return hasattr(self, key) and getattr(self, key) is not None


def generate_system_message(context_dict, search_results):
    context = context_dict if isinstance(context_dict, Context) else Context(**context_dict)

    message = [system_role]
    message.append(f"<job_writing_guide>{job_writing_summary}</job_writing_guide>")
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if search_results:
        message.append({"type": "text", "text": f"<retrieved_documentation>{search_results}</retrieved_documentation>"})

    if context.has("adaptor"):
        adaptor_string = (
            f"<adaptor>The user is using the OpenFn {context.adaptor} adaptor. Use functions provided by its API."
        )

        adaptor_docs = apollo("describe_adaptor", {"adaptor": context.adaptor})

        for doc in adaptor_docs:
            adaptor_string += f"Typescript definitions for doc {doc}"
            adaptor_string += adaptor_docs[doc]["description"]
        adaptor_string += "</adaptor>"

        message.append(adaptor_string)
    else:
        message.append("The user is using an OpenFn Adaptor to write the job.")

    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("expression"):
        message.append(f"<user_code>{context.expression}</user_code>")

    if context.has("input"):
        message.append(f"<input>The user's input data is :\n\n```{context.input}```</input>")

    if context.has("output"):
        message.append(f"<output>The user's last output data was :\n\n```{context.output}```</output>")

    if context.has("log"):
        message.append(f"<log>The user's last log output was :\n\n```{context.log}```</log>")

    return list(map(lambda text: text if isinstance(text, dict) else {"type": "text", "text": text}, message))


def build_prompt(content, history, context, is_new_conversation):
    retrieved_knowledge = None

    # Retrieve relevant docs based on the user's first message at the start of a conversation
    if is_new_conversation:
        try:
            retrieved_knowledge = retrieve_knowledge(content, adaptor=context.get("adaptor"))
        except Exception as e:
            logger.error(f"Error retrieving knowledge: {str(e)}")
    
    system_message = generate_system_message(context, retrieved_knowledge.get("search_results") if retrieved_knowledge is not None else None)

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})

    return (system_message, prompt, retrieved_knowledge)
