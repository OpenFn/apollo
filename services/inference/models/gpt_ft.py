import os

from openai import OpenAI

from util import create_logger

logger = create_logger("inference.gpt_ft")

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
)

"""
Generates a response from the finetuned GPT-3.5 Turbo model
"""


def generate(prompt, api_key) -> str:
    if api_key is None and isinstance(OPENAI_API_KEY, str):
        logger.warn("Using default API key from environment")
        api_key = OPENAI_API_KEY

    try:
        model_name = "ft:gpt-3.5-turbo-1106:openfn::8XNmyYHo"  # "ft:gpt-3.5-turbo-0613:openfn::8YbBJOlD" best 2 models
        client = OpenAI(api_key=api_key)
        logger.info(f"OpenAI {model_name} client loaded.")

        response = client.chat.completions.create(
            messages=prompt,
            model=model_name,
            temperature=0,
            max_tokens=256,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_message = f"An error occurred during GPT-ft Turbo completion: {e}"
        logger.error(error_message)
