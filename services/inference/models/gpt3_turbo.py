import os

from openai import OpenAI

from util import create_logger

logger = create_logger("inference.gpt3_turbo")


OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
)

"""
Generates a response from the GPT-3.5 Turbo model
"""


def generate(prompt, api_key) -> str:
    if api_key is None and isinstance(OPENAI_API_KEY, str):
        logger.warn("Using default API key from environment")
        api_key = OPENAI_API_KEY

    # for now we'll create a new client for every request
    # idk the pros or cons of this - check the docs I guess!
    client = OpenAI(api_key=api_key)
    logger.info(f"OpenAI GPT-3.5 Turbo client loaded.")

    try:
        logger.info("Generating")
        max_tokens = 256  # TODO maybe take an option for this?
        response = client.chat.completions.create(
            messages=prompt,
            model="gpt-3.5-turbo",
            temperature=0,
            max_tokens=max_tokens,
        )
        result = response.choices[0].message.content.strip()
        if result is None:
            logger.error("An error occurred during GPT-3.5 Turbocode generation")
        else:
            logger.info("done")

        return result
    except Exception as e:
        logger.error(f"An error occurred during GPT-3.5 Turbo code generation: {e}")
