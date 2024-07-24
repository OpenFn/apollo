import logging
from .prompt import generate_prompt
from util import createLogger

logger = createLogger("job_expression_generator.utils")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_job_prompt(adaptor, instruction, state, existing_expression):
    return generate_prompt(
        "job_expression", 
        adaptor=adaptor, 
        instruction=instruction, 
        state=state,
        existing_expression=existing_expression
    )
