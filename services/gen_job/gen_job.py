from util import DictObj, create_logger
from .prompt import generate_job_prompt
from .client import JobExpressionInferenceClient

logger = create_logger(" job_generator")

class Payload(DictObj):
    api_key: str = ""
    adaptor: str = ""
    instruction: str = ""
    state: dict = {}
    existing_expression: str = ""
    use_embeddings: bool = True

def main(dataDict) -> str:
    data = Payload(dataDict)
    logger.info("Running job expression generator with GPT-3.5 Turbo model")

    # Instantiate your custom inference client
    client = JobExpressionInferenceClient(api_key=data.api_key)

    # Generate job expression
    result = generate(client, data.adaptor, data.instruction, data.api_key, data.state, data.existing_expression, data.use_embeddings)

    logger.info("Job expression generation complete!")
    return result

def generate(client, adaptor, instruction, api_key, state, existing_expression, use_embeddings) -> str:
    # Generate prompt with optional existing expression
    prompt = generate_job_prompt(adaptor, instruction, api_key, state, existing_expression, use_embeddings)

    # Generate job expression using the custom inference client
    result = client.generate(prompt)
    return result
