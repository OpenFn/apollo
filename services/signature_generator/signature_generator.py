import inference.inference

from .prompts import generate_prompt
from .utils import (
    extract_api_info,
    parse_openapi_spec,
    trim_signature,
)
from util import DictObj

from inference import inference

from util import create_logger

logger = create_logger("signature_generator")


class Payload(DictObj):
    api_key: str
    open_api_spec: dict
    instruction: str
    model: str


def main(dataDict) -> dict:
    data = Payload(dataDict)

    # TODO: validate args and throw if anything looks amiss

    # TODO passing the spec as a DictObj fails - this is annoying.
    result = generate(data.model, dataDict["open_api_spec"], data.instruction, data.get("api_key"))

    return result


# TODO the final argument needs to be more broad to support different models
def generate(model, spec, instruction, key):
    logger.info(f"Generating signature for model {model}")

    logger.info("Parsing OpenAPI specification")
    parsed_spec = parse_openapi_spec(spec)

    logger.info("Extracting API information from parsed spec with provided instruction")
    api_info = extract_api_info(parsed_spec, instruction)

    prompt_template = "signature" if model == "gpt3_turbo" else "signature_text"
    logger.info(f"Generating {model} prompt for signature generation")

    prompt = generate_prompt(prompt_template, spec=api_info, instruction=instruction)

    signature = inference.generate(model, prompt, {"key": key})
    signature = trim_signature(signature)

    logger.info("Signature generation complete")
    return signature


# for local testing
if __name__ == "__main__":
    main({"model": "turbo"})
