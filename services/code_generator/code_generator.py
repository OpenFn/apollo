from util import DictObj, create_logger

from .utils import (
    generate_code_prompt,
)

from inference import inference


logger = create_logger("code_generator")


class Payload(DictObj):
    api_key: str
    signature: str
    model: str


# generate adaptor code based on a model and signature
def main(dataDict) -> str:
    data = Payload(dataDict)
    logger.info("Running code generator with model {}".format(data.model))
    result = generate(data.model, data.signature, data.get("api_key"))
    logger.info("Code generation complete!")
    return result


def generate(model, signature, key) -> str:
    prompt = generate_code_prompt(model, signature)

    result = inference.generate(model, prompt, {"key": key})

    return result
