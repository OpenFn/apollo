from util import DictObj, createLogger
from .prompt import generate_job_prompt
from inference import inference

logger = createLogger("job_expression_generator")

class Payload(DictObj):
    api_key: str = ""
    adaptor: str = ""
    instruction: str = ""
    state: dict = {}
    expression: str = ""

def main(dataDict) -> str:
    data = Payload(dataDict)
    logger.info("Running job expression generator with gpt3_turbo model")

    result = generate("gpt3_turbo", data.api_key, data.adaptor, data.instruction, data.state, data.expression)

    logger.info("Job expression generation complete!")
    return result

def generate(model, key, adaptor, instruction, state, existing_expression) -> str:
    # Generate prompt with optional existing expression
    prompt = generate_job_prompt(adaptor, instruction, key, state, existing_expression)

    # Generate job expression using AI model
    result = inference.generate(model, prompt, {"key": key})
    return result
