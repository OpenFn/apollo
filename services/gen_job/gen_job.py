from util import DictObj, createLogger
from .utils import generate_job_prompt
from inference import inference

logger = createLogger("job_expression_generator")


class Payload(DictObj):
    model: str = "gpt-3.5-turbo"
    api_key: str = ""
    adaptor: str = ""
    instruction: str = ""
    state: dict = {}
    expression: str = ""


def main(dataDict) -> str:
    data = Payload(dataDict)
    logger.info("Running job expression generator with model {}".format(data.model))

    result = generate(data.model, data.api_key, data.adaptor, data.instruction, data.state, data.expression)

    logger.info("Job expression generationsnn complete!")
    return result


def generate(model, key, adaptor, instruction, state, existing_expression) -> str:
    # Generate prompt with optional existing expression
    prompt = generate_job_prompt(adaptor, instruction, state, existing_expression)

    # Generate job expression using AI model
    result = inference.generate(model, prompt, {"key": key})
    return result
