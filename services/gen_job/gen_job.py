from util import DictObj, createLogger
from .prompt import generate_job_prompt, get_context
from .client import JobExpressionInferenceClient

logger = createLogger(" job_generator")

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

    # Determine context based on use_embeddings flag
    if data.use_embeddings:
        logger.info("Using embeddings to retrieve context.")
        context = get_context(data.api_key, data.instruction)
    else:
        logger.info("Skipping embeddings, using default context.")
        context = "This is a default context for generating job expressions."

    # Generate job expression
    result = generate(client, data.adaptor, data.api_key, data.instruction, data.state, data.existing_expression, context)

    logger.info("Job expression generation complete!")
    return result

def generate(client, adaptor, key, instruction, state, existing_expression, context) -> str:
    # Generate prompt with optional existing expression
    prompt = generate_job_prompt(adaptor, instruction, key, state, existing_expression, context)

    # Generate job expression using the custom inference client
    result = client.generate(prompt)
    return result
