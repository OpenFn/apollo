from .models.gpt3_turbo import generate as gpt3_turbo
from .models.codet5 import generate as codet5
from .models.gpt_ft import generate as gpt_ft
from util import DictObj

from util import create_logger

logger = create_logger("inference.prompts")


# all http calls to inference need a model and prompt, and optionally an args dict
class Payload:
    def __init__(self, dict):
        self.model = dict["model"]
        self.prompt = dict["prompt"]
        if "args" in dict:
            self.args = DictObj(dict.get("args", {}))
        else:
            self.args = DictObj({})


# This is interface for calls from js-land (via http)
def main(dataDict):
    data = Payload(dataDict)

    result = generate(data.model, data.prompt, data.args)

    logger.info(result)

    return result


# This is an internal entrypoint, used by other modules
def generate(model, prompt, args):
    result = ""

    if model == "gpt3_turbo":
        if isinstance(prompt, str):
            prompt = [{"role": "user", "content": prompt}]
        result = gpt3_turbo(prompt, args.get("key"))

    # This is likely to be unstable
    if model == "gpt3_ft":
        if isinstance(prompt, str):
            prompt = [{"role": "user", "content": prompt}]
        result = gpt_ft(prompt, args.get("key"))

    if model == "codet5":
        result = codet5(prompt)

    # TODO llama2 is broken

    return result
