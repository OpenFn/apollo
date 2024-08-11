from util import createLogger, apollo

logger = createLogger("job_expression_generator.prompts")

SYSTEM_PROMPT_TEMPLATE = """You are an agent helping a non-expert user write a job for OpenFn,
the world's leading digital public good for workflow automation.
You are helping the user write a job in OpenFn's custom DSL, which
is very similar to JAVASCRIPT. You should STRICTLY ONLY answer
questions related to OpenFn, JavaScript programming, and workflow automation and just return the javascript code.\n\n{}
"""


def get_context(api_key: str, instruction: str) -> str:
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


def generate_job_prompt(
    adaptor: str, instruction: str, api_key: str, state: dict = None, existing_expression: str = ""
) -> dict:
    context = get_context(api_key=api_key, instruction=instruction)
    adaptor_description = describe_adaptor(adaptor)

    full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            "Here is the context about job writing for and some revelant adaptor information: \n{context}"
    )

    state_info = f"Its state is: {state}." if state else ""
    expression_info = (
        f"My code currently looks like this :```{existing_expression}```\n\n You should try and re-use any relevant user code in your response if possible"
        if existing_expression
        else ""
    )

    user_prompt = f"""Write a job expression for OpenFn.
    Here is relevant context and code about the adaptor used: {adaptor_description}. 
    Refer to the adaptor code and remember to use the correct attribute IDs (add comments if attribute ID is not available). 
    Here is a simple text instruction of what the user wants: {instruction}. 
    {expression_info} 
    {state_info}. 

    Step 1: Generate the initial job expression code.

    Step 2: Analyze the generated code to ensure it matches the requirements (check for correct attribute IDs, correct syntax, and logical structure).

    Step 3: If the code does not fully meet the requirements, refine the code and repeat Step 1 and 2.

    Provide only the final, refined code as the output.
    """

    prompt = [
        {"role": "system", "content": full_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Prompt generation complete.")
    return prompt
