import os
from anthropic import Anthropic
from util import DictObj, createLogger
from .prompt import build_prompt

logger = createLogger("job_chat")

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
)

ANTHROPIC_API_KEY = os.getenv(
    "ANTHROPIC_API_KEY",
)

claude_model = "claude-3-haiku-20240307"
# claude_model = "claude-3-5-sonnet-20240620"
max_tokens = 1024


class Payload(DictObj):
    api_key: str
    content: str
    # history # list of {role , content } dicts
    # context { expression, adaptor, input, output, log  }


def main(dataDict) -> dict:
    data = Payload(dataDict)
    result = generate(
        data.content, dataDict["history"] if "history" in dataDict else [], data.context, data.get("api_key")
    )
    return result


def generate(content, history, context, api_key) -> str:
    if api_key is None and isinstance(ANTHROPIC_API_KEY, str):
        logger.warn("Using default API key from environment")
        api_key = ANTHROPIC_API_KEY

    client = Anthropic(api_key=api_key)

    logger.info("Anthropic client loaded")
    (system_message, prompt) = build_prompt(content, history, context)

    logger.info("")
    logger.info("--- PROMPT ---")
    logger.info(prompt)
    logger.info("--------------")
    logger.info("")

    try:
        logger.info("Generating")

        message = client.messages.create(
            max_tokens=max_tokens, messages=prompt, model=claude_model, system=system_message
        )

        response = []

        if response is None:
            logger.error("An error occurred during during chat generation")
        else:
            # we need to unpack the contents into a flat string
            for r in message.content:
                if r.type == "text":
                    response.append(r.text)

            response = "\n\n".join(response)

            logger.info("response from model:")
            logger.info("")
            logger.info("\n" + response)
            logger.info("")
            logger.info("done")

        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": response})

        return {"response": response, "history": history}
    except Exception as e:
        logger.error(f"An error occurred chat code generation:")
        print(e)
