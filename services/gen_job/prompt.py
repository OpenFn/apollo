import json
from util import createLogger, apollo, DictObj

logger = createLogger("job_expression_generator.prompts")

SYSTEM_PROMPT_TEMPLATE = """You are an agent helping a non-expert user write a job for OpenFn,
the world's leading digital public good for workflow automation.
You are helping the user write a job in OpenFn's custom DSL, which
is very similar to JAVASCRIPT. You should STRICTLY ONLY answer
questions related to OpenFn, JavaScript programming, and workflow automation and just return the javascript code.\n\n{}
"""

## This is used in case the embeddings are not available or use_embeddings option is false
DEFAULT_JOB_RULES = """Follow these rules while writing your job:
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
"""

def get_context(api_key: str) -> str:
    logger.info("Generating context...")
    query = f"Get the job writing guide, Usage Examples, and Job Code Examples."

    dataDict = {"query": query, "api_key": api_key}
    search_results = apollo("search", dataDict)

    return search_results

def describe_adaptor(adaptor: str) -> str:
    logger.info(f"Describing adaptor: {adaptor}")
    adaptor_docs = apollo("describe_adaptor", {"adaptor": adaptor})
    descriptions = [adaptor_docs[doc]["description"] for doc in adaptor_docs]
    return "\n".join(descriptions)

def write_to_file(content: str, filename: str = "tmp/context_and_adaptor_info.md") -> None:
    logger.info(f"Saving content to file: {filename}")
    with open(filename, "w") as file:
        file.write(content)
    logger.info("Content successfully written to file.")

def generate_job_prompt(
    adaptor: str, instruction: str, api_key: str, state: dict = None, existing_expression: str = "", use_embeddings: bool = True
) -> dict:
    adaptor_description = describe_adaptor(adaptor)

    # Determine context based on use_embeddings flag
    if use_embeddings:
        logger.info("Using embeddings to retrieve context.")
        context = get_context(api_key)
    else:
        logger.info("Skipping embeddings, using default context.")
        context = DEFAULT_JOB_RULES

    context_and_adaptor_info = f"""### Context Information ###\n\n{context}\n\n### Adaptor Description ###\n\n{adaptor_description}\n"""
    write_to_file(context_and_adaptor_info)

    full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        f"Here is the context about job writing:\n{context}\n\nHere is relevant context and code about the adaptor used:\n{adaptor_description}."
    )

    if isinstance(state, DictObj):
        state = state.toDict()
    state_info = f"The current state is: {json.dumps(state, indent=2)}. Use this to write the relevant job expression" if state else ""

    expression_info = (
        f"My code currently looks like this :```{existing_expression}```\n\n You should try and re-use any relevant user code in your response if possible"
        if existing_expression
        else ""
    )

    user_prompt = f"""Write a job expression for OpenFn.
    Refer to the adaptor code to generate the response and remember to use the correct attribute IDs (NOTE: add comments if attribute ID is not provided or you are not sure). 
    Here is a simple text instruction of what the user wants: {instruction}. 
    {expression_info} 
    {state_info}. 

    Step 1: Generate the initial job expression code.

    Step 2: Analyze the generated code to ensure it matches the requirements (check for correct attribute IDs, correct syntax, and logical structure).

    Step 3: If the code does not fully meet the requirements, refine the code and repeat Step 1 and 2.

    Strictly provide only the final, refined code as the output.
    """

    prompt = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Prompt generation complete.")
    return prompt
