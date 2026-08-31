"""Prompt construction for the job_chat service."""

import json

import sentry_sdk
from langfuse import observe
from search_adaptor_docs.search_adaptor_docs import fetch_signatures
from util import AdaptorSpecifier, ApolloError, create_logger, get_db_connection
from yaml_utils import normalize_name, redact_job_bodies

from .retrieve_docs import retrieve_knowledge

logger = create_logger("job_chat.prompt")

_role_before_scope = """
You are a software engineer helping a non-expert user write a job for our platform.
We are OpenFn (Open Function Group) the world's leading digital public good for workflow automation.

Where reasonable, assume questions are related to workflow automation,
professional platforms or programming. You may provide general information around these topics,
e.g. general programming assistance unrelated to job writing.
If a question is entirely irrelevant, do not answer it.

Keep your responses concise and lead with the answer. Explain only as much as
the user's question needs. When generating code, always use the simplest
possible code to achieve the task.

Do not thank the user or be obsequious. Address the user directly.

You are embedded in our app for building workflows. Our app will provide the
history of each chat session to you. Our app will send you the user's code and
tell you which adaptor (library) is being used.
Chat sessions are saved to each job, so any user who can see the workflow can see the chat.

Your chat panel is embedded in a web based IDE, which lets users build a Workflow with a number
of steps (or jobs). There is a code editor next to you, which users can copy and paste code into.
Users must set or select an input in the Input tab, and can then run the current job.
"""

# Production only. In global chat's subagent mode, structure requests are
# handled via edit_workflow, so this scope restriction is omitted entirely
# rather than contradicted.
production_scope_instructions = """
You ONLY help with job code. Do NOT help with overall workflow structure.
If the user wants to add/remove/edit workflow steps, tell them to navigate to the workflow overview.
"""

_role_after_scope = """
Users can Flag any answers that are not helpful, which will help us build a better prompt for you.

<context tags>
The system will provide you with various pieces of context about the user's job using XML tags:

- <user_code>: The current job code the user is working on. This is the code they want help with.
- <adaptor>: Documentation for the adaptor (library) the user is using. Reference this when suggesting functions.
- <input>: Sample input data the user is testing with. Shows what data structure enters the job.
- <output>: The output data from a previous run. Shows what the job produced.
- <run_logs>: Execution logs from when the user ran their job. These contain console.log output,
  error messages, and system logs. Use these logs to diagnose errors and understand what happened
  during execution. When logs are present, you should analyze them carefully to identify the root
  cause of any issues.

When the user asks you to check logs or debug an error, the <run_logs> tag will contain the
relevant execution information. Pay close attention to error messages, stack traces, and the
sequence of log statements to understand what went wrong.

Earlier turns may have pertained to different context (workflow structure or other job steps) that is no longer
attached. Any previously generated code has been redacted from history. Some turns may have a [pg:...]
prefix showing the user's page context at that time.
</context tags>
"""

system_role = _role_before_scope + production_scope_instructions + _role_after_scope
subagent_system_role = _role_before_scope + _role_after_scope

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

<execution model>
A job runs in two phases:
1. Load time: the file is compiled and evaluated top to bottom to collect the pipeline of operations. All operation arguments are evaluated immediately, before any data exists, but operations are not executed.
2. Run time: the runtime calls each operation in order, passing each one the state returned by the previous.

This means:
- Operation execution order may differ from statement declaration order.
- A bare state reference in `get(state.x)` in an operation's arguments is undefined at load time. Defer it with a function, `get(state => state.x)`, or the `$` lazy-state shorthand `get($.x)`, which means `get(state => state.x)`. Note that `$` is readonly and only valid inside an operation's arguments, nowhere else (no `const x = $.y`).
- Never invoke an operation yourself: `post('/x', ...)(state)` bypasses the runtime execution order and is bad practice. It can be tempted to do this when nesting operations within callbacks for iteration. Usually this can be resolved by breaking nesting and moving the operation to the top level.
- `fn()` and `.then()` callbacks must return state. When building a new object, spread the old one (`return { ...state, data: mapped }`) so keys like configuration survive.
- Most operations overwrite `state.data` with its result: after your create/update/post, `state.data` is that call's response, not your input. Copy values you need later onto another state key first.
</execution model>
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
<workflow guide>
A job is just one step in a workflow (or pipeline). Workflows are used
to automate processes and migrate data from system to system.

In OpenFn, each step works with a single backend system, or adaptor. Data is shared
between steps through the state object.

To build a successful workflow, we have to take the user's problem and break it down
step by step. Focus on one bit at a time. For example, when uploading from CommCare to Salesforce, we have to:
1. Download our data from CommCare in one step
2. Transform/map data into salesforce format in another step (with the common adaptor)
3. Upload the transformed data into salesforce in the final step
</workflow guide>
"""

# Appended in subagent mode only (when job_chat is called from global_chat).
subagent_mode_instructions = """
<beyond_this_step>
The workflow has other steps, but your edit_job tool edits THIS step only.
Decide by where the change lands:

- Change lands in THIS step (or nothing needs changing): handle it here. Read
  any other step with `inspect_job_code` whenever it helps — what an upstream
  step outputs, keeping style or field names consistent, finding code the user
  mentions that is not in <user_code>.
- Change lands anywhere else — workflow structure (add/remove/rename steps,
  triggers, edges, adaptors) or another step's code, even code the user calls
  "this step": call `edit_workflow` as your very first action, before any
  reply text (at most exactly: "I'll take a look at your workflow.").

If the user mentions code you can't find in <user_code>, assume it lives in
another step — never reply that it isn't here.
</beyond_this_step>
"""

# Response contract, appended last in the system message.
output_format = """
<response_format>
Reply to the user in normal text. Markdown is fine, including ```js fenced code
blocks for illustrative examples. That text IS your answer — you do not need to
call any tool just to talk, explain, or show an example.

Call the `edit_job` tool ONLY when the user wants their CURRENT job code changed.
When you do, pass ALL the edits in a SINGLE call via the `code_edits` array. Do
NOT call `edit_job` to show an example — examples belong in your text reply. If the
user only wants an explanation or to be shown something, just answer in text and
do not call the tool.

Describe edits in the future tense ("I'll add X"), not the past ("I added X").

Each item in `code_edits`:
- {"action": "replace", "old_code": "<exact code to find>", "new_code": "<replacement>"}
- {"action": "rewrite", "new_code": "<complete new code>"}

If the current job is EMPTY (no code at all), you MUST use the "rewrite" action
with the complete code. There is nothing to "replace" in an empty job, so a
"replace" edit will not apply.

<code editing rules>
- old_code must match the user's code EXACTLY, including all whitespace and indentation.
- Edits apply sequentially — later edits work on the already-modified code.
- If old_code isn't found exactly, the edit fails safely rather than corrupting the file.
- To insert, replace an anchor with itself plus the new code.
- INCLUDE AMPLE SURROUNDING CONTEXT in old_code so it matches a single, unique location
  (comments, variable declarations, neighbouring lines). If in doubt, use "rewrite".
</code editing rules>
</response_format>
"""

error_correction_system_prompt = """
You are a code edit correction assistant. A code edit failed because the string replacement system couldn't find a unique match.

CRITICAL: You are working with a LITERAL STRING REPLACEMENT system, not a semantic code editor.

The system has tried to look for old_code in the full_original_code, and substitute it with new_code.
Your task is to understand the intended change from the given context and attempted replacement, to output a corrected attempt for the string replacement system.
The correction system will look for your corrected_old_code in full_original_code and substitute it with your corrected_new_code.

Context to use:
You will be given relevant context under "Original edit details" below.
This may include an explanation of attempted changes. Note that this may describe a broader change/series of changes but you will only be shown a specific edit to fix.

Common issues:
1. "old_code not found" - the old_code doesn't exactly match what's in the file
  --> Look at the full code and find the closest matching section
2. "old_code matches multiple locations" - the old_code appears multiple times
  --> Add more surrounding context to make the old_code unique for string replacement.
      **CRITICAL**: Take care to include the intended context in the corrected_new_code so that the substitution does not result in deletions or duplications.
3. "Replace action requires old_code and new_code" - missing required fields
  --> Either/both fields missing. Use the given context and full code to fill these.

It is important to:
- Preserve the intended change from the original new_code
- Maintain exact whitespace and formatting
- Include enough context in old_code to make it unique

Output JSON format:
{
  "explanation": "1-sentence explanation of the correction",
  "corrected_old_code": "corrected old code with proper context",
  "corrected_new_code": "corrected new code"
}

**Output ONLY the JSON object**
Your ENTIRE response must be a single JSON object and nothing else: no prose before
or after it, no markdown code fences. The first character must be `{` and the last `}`.
Your answer MUST be parsable with json.loads():
- Escape all newlines as \\n (one backslash followed by n)
- Escape all double quotes as \\"  (one backslash followed by double quotation mark)
- Do not include unescaped control characters in any string value.
- When you include code in a string, ensure it is a single line with \\n for line breaks.

ALWAYS use \\n instead of actual newlines:
THIS IS WRONG:
"corrected_new_code": "function() {
  return true;
}"

THIS IS CORRECT:
"corrected_new_code": "function() {\\n  return true;\\n}"
"""


class Context:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def has(self, key):
        return hasattr(self, key) and getattr(self, key) is not None


def build_focus_line(viewing, focused):
    """One sentence orienting the model to what the user has on screen, and which
    step it can edit when that differs.

    `viewing` (router-only) is the on-screen step name, the literal "canvas", or
    None when the caller can't tell; `focused` is the editable step. When both
    are a step and coincide (the common case) they fuse into one clause; they
    diverge only when the request targets a step other than the one open.

    Returns "" when there is nothing worth stating (no viewing info): the model
    works from <user_code> and the tools, and we avoid narrating editing plumbing
    the model could echo back to the user.
    """
    if viewing and viewing != "canvas":
        if not focused:
            return f"The user has the '{viewing}' step's code open."
        if normalize_name(viewing) == normalize_name(focused):
            return f"The user has the '{viewing}' step's code open — that's the step you're currently editing."
        return f"The user has the '{viewing}' step open, but the step you're editing is '{focused}' — likely what their request is about."
    if viewing == "canvas":
        if focused:
            return f"The user is viewing the workflow canvas, not a specific step; the '{focused}' step is the one you're currently editing."
        return "The user is viewing the workflow canvas."
    return ""


def generate_system_message(context_dict, search_results, download_adaptor_docs=True, stream_manager=None,
                            workflow_yaml=None, subagent=False):
    context = context_dict if isinstance(context_dict, Context) else Context(**(context_dict or {}))

    message = [subagent_system_role if subagent else system_role]
    message.append(f"<job_writing_guide>{job_writing_summary}</job_writing_guide>")
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if search_results:
        search_results = format_search_results(search_results)
        message.append(f"<retrieved_documentation>General OpenFn documentation search results. These cover platform concepts only — not adaptor-specific APIs, which are included separately. Treat with caution if not relevant to the user's situation.\n\n{search_results}</retrieved_documentation>")
        message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("adaptor"):
        adaptor_string = (
            f"<adaptor>The user is using the OpenFn {context.adaptor} adaptor. Use functions provided by its API.\n\n"
        )

        try:
            conn = get_db_connection()

            try:
                try:
                    adaptor = AdaptorSpecifier(context.adaptor)

                    signatures = fetch_signatures(adaptor, conn, auto_load=download_adaptor_docs)

                    if signatures:
                        adaptor_string += "These are the available functions in the adaptor:\n\n"
                        for func_name, signature in signatures.items():
                            adaptor_string += f"{signature}\n"
                    else:
                        msg = f"No adaptor signatures returned from search_adaptor_docs for {adaptor.specifier}"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        sentry_sdk.set_context("adaptor_context", {
                            "adaptor_name": adaptor.name,
                            "version": adaptor.version,
                            "parsed_from": context.adaptor,
                        })
                        adaptor_string += "The user is using an OpenFn Adaptor to write the job."
                except Exception as parse_error:
                    msg = f"Failed to parse adaptor string ({type(parse_error).__name__})"
                    logger.warning(msg)
                    sentry_sdk.capture_message(msg, level="warning")
                    sentry_sdk.set_context("adaptor_context", {
                        "parsed_from": context.adaptor,
                        "error": type(parse_error).__name__,
                    })
                    adaptor_string += "The user is using an OpenFn Adaptor to write the job."
            finally:
                conn.close()
        except ApolloError as e:
            logger.warning(f"Database not available ({type(e).__name__})")
            adaptor_string += "The user is using an OpenFn Adaptor to write the job."
        except Exception as e:
            logger.warning(f"Could not fetch adaptor docs ({type(e).__name__})")
            adaptor_string += "The user is using an OpenFn Adaptor to write the job."

        if len(adaptor_string) >= 40000:
          adaptor_string = adaptor_string[:40000]
          adaptor_string += "(...)"

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
        message.append(f"""<run_logs>
IMPORTANT: The user has included execution logs from their last workflow run below.
These logs contain the actual runtime output including console.log statements, error messages,
and system information. When debugging, analyze these logs carefully to identify:
- Error messages and their root causes
- The sequence of operations that executed
- Any unexpected behavior or missing output
- Stack traces if errors occurred

```{context.log}```
</run_logs>""")

    if subagent:
        message.append(subagent_mode_instructions)
        if workflow_yaml:
            # `focused` is the editable step; `viewing` (router-only) is what the
            # user actually has on screen — a step's code or the literal "canvas".
            # Grounding focus in their view lets a bare "this step" resolve to
            # what they're looking at. Both may be absent (planner/prod, or an
            # unresolved page), in which case build_focus_line returns "".
            focused = context.job_key if context.has("job_key") else (
                context.page_name if context.has("page_name") else None)
            viewing = context.viewing if context.has("viewing") else None
            focus = build_focus_line(viewing, focused)
            header = ["The full workflow, job code redacted."]
            if focus:
                header.append(focus)
            header.append("READ other steps' code with `inspect_job_code` when the request refers to them.")
            redacted = redact_job_bodies(workflow_yaml)
            message.append(
                f"<workflow_structure>\n{' '.join(header)}\n\n{redacted}\n</workflow_structure>",
            )

    # Output contract goes LAST so it is the final, most prominent instruction.
    message.append(output_format)

    return list(map(lambda text: text if isinstance(text, dict) else {"type": "text", "text": text}, message))

def format_search_results(search_results):
    return '\n'.join([
        f'search result: "{result.get("text")}", source: "{result.get("metadata", {}).get("doc_title", "")} {result.get("medatada", {}).get("docs_type", "")}"'
        for result in search_results
    ])

@observe(name="job_chat_build_prompt")
def build_prompt(content, history, context, rag=None, api_key=None, stream_manager=None, download_adaptor_docs=True, refresh_rag=False,
                 workflow_yaml=None, subagent=False):
    retrieved_knowledge = {
        "search_results": [],
        "search_results_sections": [],
        "search_queries": [],
        "config_version": "",
        "prompts_version": "",
        "usage": {
            "needs_docs": {},
            "generate_queries": {},
        },
    }

    # Run RAG if: (a) no RAG data provided, OR (b) refresh_rag flag is True
    if rag and not refresh_rag:
        retrieved_knowledge = rag
    else:
      try:
          retrieved_knowledge = retrieve_knowledge(
              content=content,
              history=history,
              code=context.get("expression", ""),
              adaptor=context.get("adaptor", ""),
              api_key=api_key,
              stream_manager=stream_manager,
          )
      except Exception as e:
          logger.error(f"Error retrieving knowledge ({type(e).__name__})")

    system_message = generate_system_message(
        context_dict=context,
        search_results=retrieved_knowledge.get("search_results") if retrieved_knowledge is not None else None,
        download_adaptor_docs=download_adaptor_docs,
        stream_manager=stream_manager,
        workflow_yaml=workflow_yaml,
        subagent=subagent)

    prompt = []
    prompt.extend(history)
    # Per-message reminder on the CURRENT turn only (the last thing the model
    # reads). It is conditional by design — we do NOT want to force a tool call,
    # only remind the model to route an actual code change through `edit_job`.
    # Added only to the message sent to the model; the stored history (built in
    # generate() from the raw content) omits it, so it never accumulates.
    reminder = "Reply in text. If this requires changing the job code, also call the `edit_job` tool to apply the change."
    if subagent:
        reminder += (
            " If it needs changes beyond this step's code, call `edit_workflow` first;"
            " to merely read another step (to answer, or to edit this one), use `inspect_job_code`."
        )
    prompt.append({
        "role": "user",
        "content": f"{content}\n\n{reminder}",
    })

    return (system_message, prompt, retrieved_knowledge)

def build_error_correction_prompt(content: str, error_message: str, old_code: str, new_code: str, full_code: str, text_explanation: str):
    """Build a prompt for correcting code edit errors."""

    system_message = [{"type": "text", "text": error_correction_system_prompt}]

    user_content = f"""A code edit failed with this error: "{error_message}"

Original edit details:
- old_code:\n{json.dumps(old_code)}
- attempted to replace the above with new_code:\n{json.dumps(new_code)}
- the user's original message:\n{content}
- explanation of (all) attempted changes:\n{text_explanation}
- full_original_code:
```
{full_code}
```

Please provide corrected old_code and new_code that will successfully apply the intended change with string replacement."""

    prompt = [{"role": "user", "content": user_content}]
    # Sizes only: this is the user's job body plus the adaptor docs. Measured
    # on the two strings; `system_message` is a one-element list, so measuring
    # that reported 1 on every request.
    logger.info(
        f"prompt built: {len(error_correction_system_prompt)} characters of system "
        f"message, {len(user_content)} of user content",
    )
    return (system_message, prompt)
