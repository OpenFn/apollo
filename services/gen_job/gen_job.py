from util import DictObj, createLogger
from .prompt import generate_job_prompt
from .client import JobExpressionInferenceClient

logger = createLogger("job_expression_generator")


class Payload(DictObj):
    api_key: str = ""
    adaptor: str = ""
    instruction: str = ""
    state: dict = {}
    existing_expression: str = ""


def main(dataDict) -> str:
    data = Payload(dataDict)
    logger.info("Running job expression generator with GPT-3.5 Turbo model")

    # Instantiate your custom inference client
    client = JobExpressionInferenceClient(api_key=data.api_key)

    # Generate job expression
    result = generate(client, data.adaptor, data.api_key, data.instruction, data.state, data.existing_expression)

    logger.info("Job expression generation complete!")
    return result


def generate(client, adaptor, key, instruction, state, existing_expression) -> str:
    # Generate prompt with optional existing expression
    prompt = generate_job_prompt(adaptor, instruction, key, state, existing_expression)

    # Generate job expression using the custom inference client
    result = client.generate(prompt)
    return result
