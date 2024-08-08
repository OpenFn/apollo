from util import createLogger, apollo

logger = createLogger("job_expression_generator.prompts")

SYSTEM_PROMPT_TEMPLATE = """You are an agent helping a non-expert user write a job for OpenFn,
the world's leading digital public good for workflow automation.
You are helping the user write a job in OpenFn's custom DSL, which
is very similar to JAVASCRIPT. You should STRICTLY ONLY answer
questions related to OpenFn, JavaScript programming, and workflow automation.
Follow these rules while writing your job: 

Each job uses exactly one Adaptor to perform its task. The Adaptor provides a
collection of Operations (helper functions) which makes it easy to communicate with
a data source. The adaptor API for this job is provided below.

A job MUST NOT include an import or require statement.
A job MUST NOT use the execute() function.
A job MUST only contain function calls at the top level.
A job MUST NOT include any other JavaScript statements at the top level.
A job MUST NOT include assignments at the top level.
A job SHOULD NOT use async/await or promises.
A job SHOULD NOT use alterState, instead it should use fn for data transformation.

Here is more context about job writing and some revelant adaptor information:\n {}
"""


def get_context(api_key: str, instruction: str) -> str:
    logger.info("Generating context...")
    query = f"Get the job writing guide, Usage Examples, and Job Code Examples."

    data_dict = {"query": query, "api_key": api_key}
    search_results = apollo("search", data_dict)

    return search_results


def describe_adaptor(adaptor: str) -> str:
    logger.info(f"Describing adaptor: {adaptor}")
    adaptor_docs = apollo("describe_adaptor", {"adaptor": adaptor})
    descriptions = [adaptor_docs[doc]["description"] for doc in adaptor_docs]
    return "\n".join(descriptions)


def generate_job_prompt(
    adaptor: str, instruction: str, api_key: str, state: dict = None, existing_expression: str = ""
) -> dict:
    context = get_context(api_key=api_key, instruction=instruction)
    adaptor_description = describe_adaptor(adaptor)

    full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(f"{context}\n\nAdaptor Description:\n{adaptor_description}")

    state_info = f"Its current state is: {state}" if state else ""
    expression_info = (
        f"My code currently looks like this :```{existing_expression}```\n\n You should try and re-use any relevant user code in your response"
        if existing_expression
        else ""
    )

    user_prompt = f"Write a job in OpenFn's custom dsl and use the given job writing context and adaptor information. {expression_info}. {state_info} and it uses the following adaptor: {adaptor}. Here is a simple text instruction what the user wants, refer to this but keep in mind the actual adaptor information and job writing rules: {instruction}"

    prompt = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Prompt generation complete.")
    return prompt
