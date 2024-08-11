import os
from openai import OpenAI
from util import createLogger

logger = createLogger("job_expression_generator")

# Load API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

class JobExpressionInferenceClient:
    def __init__(self, api_key=None):
        # Use provided API key or fallback to environment key
        self.api_key = api_key or OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("API key must be provided either as an argument or through environment variable 'OPENAI_API_KEY'.")
        
        self.client = OpenAI(api_key=self.api_key)
        logger.info(f"OpenAI GPT-3.5 Turbo client initialized for job expression generation.")

    def generate(self, prompt, max_tokens=256, temperature=0.5) -> str:
        try:
            logger.info("Generating job expression from GPT-3.5 Turbo model.")
            response = self.client.chat.completions.create(
                messages=prompt,
                model="gpt-3.5-turbo",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            result = response.choices[0].message.content.strip()
            if not result:
                logger.error("Received empty response from GPT-3.5 Turbo.")
                return None
            
            logger.info("Job expression generation successful.")
            return result
        
        except Exception as e:
            logger.error(f"An error occurred during GPT-3.5 Turbo job expression generation: {e}")
            return None
