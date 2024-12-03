import logging
from .prompts import generate_prompt

from util import create_logger

logger = create_logger("code_generator.utils")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_code_prompt(model, signature):
    prompt_template = "code" if model == "gpt3_turbo" else "code_ft" if model == "gpt_ft" else "code_text"
    return generate_prompt(prompt_template, signature=signature)


def generate_test_prompt(model, implementation):
    return generate_prompt("test", implementation=implementation)


def trim_test(test):
    end_tokens = "/* Test */"
    if end_tokens in test:
        logger.info("Trimming the end token from test")
        return test[test.find(end_tokens) :]
    else:
        logger.warning("End token not found in the test")
        return test
