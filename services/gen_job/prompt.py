import search.search as search
from util import createLogger

logger = createLogger("job_expression_generator.prompts")

system_prompt = """You are an agent helping a non-expert user write a job for OpenFn,
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

Here is more context about job writting. {}
"""


def getContext(api_key, adaptor, instruction) -> str:
    logger.info("Generating context...")
    query = "Get the job writing guide, Usage Examples, and Job Code Examples. It should include {} adaptor information along with examples to {}.".format(
        adaptor, instruction
    )

    dataDict = {"query": query, "api_key": api_key}
    search_results = search.main(dataDict)

    return search_results


def generate_job_prompt(adaptor, instruction, state, existing_expression, key) -> str:
    context = getContext(api_key=key, adaptor=adaptor, instruction=instruction)

    full_system_prompt = system_prompt.format(context)

    user_prompt = "Write a job in OpenFn's custom DSL, which is very similar to JavaScript, follow all the rules and refer to the given context only. The job should be as similar to the following: {}. Its state is: {} and it uses the following adaptor: {}.".format(
        existing_expression, state, adaptor
    )

    prompt = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Prompt generation complete.")
    return prompt
