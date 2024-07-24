import copy
from util import createLogger

logger = createLogger("job_expression_generator.prompts")

prompts = {
    "job_expression": (
        "You are a helpful Javascript code assistant.",
        "Below is a description of a task along with the adaptor specification and sample input data. "
        "Generate a JavaScript job expression that performs the task described. Ensure the job expression "
        "follows the conventions defined in the adaptor and job expression documentation.\n\n"
        "Adaptor: {adaptor}\n"
        "instruction: {instruction}\n"
        "Sample Input: {state}\n"
        "{existing_expression_part}"
        "====",
    ),
}

def generate_prompt(prompt_name: str, **kwargs) -> str:
    logger.info(f"Generating prompt for: {prompt_name}")
    system_prompt, user_prompt_template = prompts.get(prompt_name, ("", ""))
    
    if user_prompt_template is None:
        raise ValueError(f"Prompt '{prompt_name}' not found.")
    
    prompt = copy.deepcopy(user_prompt_template)
    user_prompt = prompt.format(
        adaptor=kwargs.get("adaptor", ""), 
        instruction=kwargs.get("instruction", ""), 
        state=kwargs.get("state", ""),
        existing_expression_part=f"Existing Expression: {kwargs.get('existing_expression', '')}\n" if kwargs.get('existing_expression') else ""
    )
    
    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    logger.info(f"Prompt generation complete for: {prompt_name}")
    return prompt
