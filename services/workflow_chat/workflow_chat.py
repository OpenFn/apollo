import json
import os
from typing import List, Optional, Dict, Any
import yaml
from dataclasses import dataclass
from anthropic import (
    Anthropic,
    APIConnectionError,
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    UnprocessableEntityError,
    RateLimitError,
    InternalServerError,
)
from util import ApolloError, create_logger
from .gen_project_prompt import build_prompt
from .available_adaptors import available_adaptors

logger = create_logger("workflow_chat")

@dataclass
class Payload:
    """
    Data class for validating and storing input parameters.
    Required fields will raise TypeError if not provided.
    """

    content: Optional[str] = None
    errors: Optional[str] = None
    existing_yaml: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """
        Create a Payload instance from a dictionary, validating required fields.
        """

        return cls(
        content=data.get("content"),
        errors=data.get("errors"),
        existing_yaml=data.get("existing_yaml"),
        history=data.get("history", []),
        api_key=data.get("api_key")
    )


@dataclass
class ChatConfig:
    model: str = "claude-3-7-sonnet-20250219"
    max_tokens: int = 1024
    api_key: Optional[str] = None

@dataclass
class ChatResponse:
    content: str
    content_yaml: str
    history: List[Dict[str, str]]
    usage: Dict[str, Any]

class AnthropicClient:
    def __init__(self, config: Optional[ChatConfig] = None):
        self.config = config or ChatConfig()
        self.api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)

    def generate(
        self, content: str = None, existing_yaml: str = None, errors: Optional[str] = None, history: Optional[List[Dict[str, str]]] = None) -> ChatResponse:
        """Generate a response using the Claude API. Retry up to 2 times if YAML/JSON parsing fails."""
        history = history.copy() if history else []
        system_message, prompt = build_prompt(content=content, existing_yaml=existing_yaml, errors=errors, history=history)

        accumulated_usage = {
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
            'input_tokens': 0,
            'output_tokens': 0
        }

        max_retries = 1
        for attempt in range(max_retries + 1):  
            message = self.client.messages.create(
                max_tokens=self.config.max_tokens, messages=prompt, model=self.config.model, system=system_message
            )

            # Track usage from this attempt
            if hasattr(message, "usage"):
                usage = message.usage.model_dump()
                for key in accumulated_usage:
                    if key in usage:
                        accumulated_usage[key] += usage[key]

            response_parts = []
            for content_block in message.content:
                if content_block.type == "text":
                    response_parts.append(content_block.text)
                else:
                    logger.warning(f"Unhandled content type: {content_block.type}")

            response = "\n\n".join(response_parts)
            response_text, response_yaml = self.split_format_yaml(response)
            
            # If YAML parsing succeeded or we're on the last attempt, return the result
            if response_yaml is not None or attempt == max_retries:
                updated_history = history + [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": response},
                ]
                
                return ChatResponse(
                    content=response_text,
                    content_yaml=response_yaml,
                    history=updated_history,
                    usage=accumulated_usage,
                )
            
            # Otherwise, log and retry
            logger.warning(f"YAML parsing failed, retrying generation (attempt {attempt+1}/{max_retries})")

    def split_format_yaml(self, response):
        """Split text and YAML in response and format the YAML."""
        try:
            # Try to parse the response as JSON
            response_data = json.loads(response)
            
            # Extract text and yaml from the JSON
            output_text = response_data.get("text", "").strip()
            output_yaml = response_data.get("yaml", "")
            
            if output_yaml:
                # Decode the escaped newlines into actual newlines if needed
                output_yaml = output_yaml.encode().decode("unicode_escape")
                # Parse YAML string into Python object
                output_yaml = yaml.safe_load(output_yaml)
                # Log if using invalid adaptors
                self.validate_adaptors(output_yaml)
                # Convert back to YAML string with preserved order
                output_yaml = yaml.dump(output_yaml, sort_keys=False)
            return output_text, output_yaml
        except Exception as e:
            logger.error(f"Error during JSON parsing: {str(e)}")
        
        return output_text, output_yaml
    
    def validate_adaptors(self, yaml_data):
        """Validate that all adaptors in the YAML are on the approved list."""
        valid_adaptors = list(available_adaptors.keys())
        
        if yaml_data and 'jobs' in yaml_data:
            jobs = yaml_data['jobs']
            for job_key, job_data in jobs.items():
                if 'adaptor' in job_data:
                    adaptor = job_data['adaptor']
                    if adaptor not in valid_adaptors:
                        logger.warning(f"Invalid adaptor found in job '{job_key}': {adaptor}")

def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        data = Payload.from_dict(data_dict)

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(content=data.content, existing_yaml=data.existing_yaml, errors=data.errors, history=data.history)

        return {"response": result.content, "response_yaml": result.content_yaml, "history": result.history, "usage": result.usage}

    except ValueError as e:
        raise ApolloError(400, str(e), type="BAD_REQUEST")

    except APIConnectionError as e:
        raise ApolloError(
            503,
            "Unable to reach the Anthropic AI Service",
            type="CONNECTION_ERROR",
            details={"cause": str(e.__cause__)},
        )
    except AuthenticationError as e:
        raise ApolloError(401, "Authentication failed", type="AUTH_ERROR")
    except RateLimitError as e:
        raise ApolloError(
            429, "Rate limit exceeded, please try again later", type="RATE_LIMIT", details={"retry_after": 60}
        )
    except BadRequestError as e:
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except PermissionDeniedError as e:
        raise ApolloError(403, "Not authorized to perform this action", type="FORBIDDEN")
    except NotFoundError as e:
        raise ApolloError(404, "Resource not found", type="NOT_FOUND")
    except UnprocessableEntityError as e:
        raise ApolloError(422, str(e), type="INVALID_REQUEST")
    except InternalServerError as e:
        raise ApolloError(500, "The Anthropic AI Service encountered an error", type="PROVIDER_ERROR")
    except Exception as e:
        logger.error(f"Unexpected error during chat generation: {str(e)}")
        raise ApolloError(500, str(e))
