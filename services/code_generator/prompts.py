import copy
from util import create_logger

logger = create_logger("code_generator.prompts")


prompts = {
    "test": (
        "You are a helpful Javascript code assistant.",
        "Below is a Javascript Implementation with JsDoc that performs a task. "
        "Write a Test.js that appropriately tests the implementation.\n\n{implementation}\n/* Test */\n",
    ),
    "code_ft": (
        "You are a helpful Javascript code assistant.",
        "Below is a TypeScript Declaration with JsDoc that describes a tasks. "
        "Write a Javascript Implementation that appropriately answers the task.\n\n{signature}\n/* JavaScript Implementation */\n",
    ),
    "code": (
        "You are a helpful Javascript code assistant.",
        "Generate JavaScript implementation for the OpenFn function signature below. "
        "The comments above the function signature describe what it does.\n"
        "Guides:\n"
        "- Use async/await instead of promise chains.\n"
        "- Create a new state via spread syntax: `const newState = {{ ...state, data: data }}`.\n"
        "- Ensure you import and use http from @openfn/language-common for HTTP requests (assume available).\n"
        "- Copy the comments (see /**/) and include right above function definition.\n"
        "- Start with any imports.\n"
        "- Code should contain only JS, functions, and imports. No type definition.\n\n"
        "### Signature:\n{signature}\n\n### Implementation: \n====",
    ),
}


def generate_prompt(prompt_name: str, **kwargs) -> str:
    """
    Generate a prompt from a specified template filled with provided variables.
    """
    logger.info(f"Generating prompt for: {prompt_name}")
    if prompt_name == "code_text":
        system_prompt, user_prompt_template = prompts.get("code", ("", ""))
    else:
        system_prompt, user_prompt_template = prompts.get(prompt_name, ("", ""))
    if user_prompt_template is None:
        raise ValueError(f"Prompt '{prompt_name}' not found.")
    prompt = copy.deepcopy(user_prompt_template)
    user_prompt = ""

    if prompt_name == "test":
        user_prompt = prompt.replace("implementation", kwargs.get("implementation", ""))
    else:
        user_prompt = prompt.replace("signature", kwargs.get("signature", ""))
        if prompt_name == "code_text":
            logger.info(f"Prompt generation complete for: {prompt_name}")
            return user_prompt

    prompt = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {"role": "user", "content": user_prompt},
    ]
    logger.info(f"Prompt generation complete for: {prompt_name}")
    return prompt
