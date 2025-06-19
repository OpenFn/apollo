import json
import os
import re
import unicodedata
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
            api_key=data.get("api_key"),
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
        self,
        content: str = None,
        existing_yaml: str = None,
        errors: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> ChatResponse:
        """Generate a response using the Claude API. Retry up to 2 times if YAML/JSON parsing fails."""
        history = history.copy() if history else []
        
        # Extract and preserve existing code if yaml exists
        preserved_codes = {}
        processed_existing_yaml = existing_yaml
        
        if existing_yaml and existing_yaml.strip():
            try:
                yaml_data = yaml.safe_load(existing_yaml)
                preserved_codes = self.extract_job_codes(yaml_data)
                if preserved_codes:
                    processed_existing_yaml = self.replace_codes_with_placeholders(yaml_data, preserved_codes)
            except Exception as e:
                logger.warning(f"Could not parse existing YAML for code extraction: {e}")
        
        system_message, prompt = build_prompt(
            content=content, 
            existing_yaml=processed_existing_yaml, 
            errors=errors, 
            history=history
        )

        accumulated_usage = {
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
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
            response_text, response_yaml = self.split_format_yaml(response, preserved_codes)

            # If YAML parsing succeeded or we're on the last attempt, return the result
            if response_yaml is not None or attempt == max_retries:
                updated_history = history + [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": response},
                ]

                return ChatResponse(
                    content=response_text,
                    content_yaml=response_yaml or None,
                    history=updated_history,
                    usage=accumulated_usage,
                )

            # Otherwise, log and retry
            logger.warning(f"YAML parsing failed, retrying generation (attempt {attempt+1}/{max_retries})")

    def sanitize_job_names(self, yaml_data):
        """Sanitize job names by removing special characters and normalizing diacritics."""
        if yaml_data and "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            for job_key, job_data in jobs.items():
                if "name" in job_data:
                    original_name = str(job_data["name"])
                    # Normalize unicode characters (removes diacritics)
                    normalized = unicodedata.normalize('NFKD', original_name)
                    ascii_name = normalized.encode('ascii', 'ignore').decode('ascii')
                    # Keep only alphanumeric, spaces, hyphens, and underscores
                    sanitized_name = re.sub(r'[^a-zA-Z0-9\s\-_]', '', ascii_name)
                    
                    job_data["name"] = sanitized_name
                    
                    if original_name != sanitized_name:
                        logger.info(f"Sanitized job name: '{original_name}' -> '{sanitized_name}'")

    def split_format_yaml(self, response, preserved_codes=None):
        """Split text and YAML in response and format the YAML."""
        output_text, output_yaml = "", None

        try:
            # Try to parse the response as JSON
            response_data = json.loads(response)

            # Extract text and yaml from the JSON
            output_text = response_data.get("text", "").strip()
            output_yaml = response_data.get("yaml", "")

            if output_yaml and output_yaml.strip():
                # Parse YAML string into Python object
                output_yaml = yaml.safe_load(output_yaml)

                self.validate_adaptors(output_yaml)
                self.sanitize_job_names(output_yaml)
                self.process_job_bodies(output_yaml, preserved_codes)
                
                # Convert back to YAML string with preserved order
                output_yaml = yaml.dump(output_yaml, sort_keys=False)
            else:
                output_yaml = ""
                
        except Exception as e:
            logger.error(f"Error during JSON parsing: {str(e)}")

        return output_text, output_yaml

    def validate_adaptors(self, yaml_data):
        """Validate that all adaptors in the YAML are on the approved list."""
        valid_adaptors = list(available_adaptors.keys())

        if yaml_data and "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            for job_key, job_data in jobs.items():
                if "adaptor" in job_data:
                    adaptor = job_data["adaptor"]
                    if adaptor not in valid_adaptors:
                        logger.warning(f"Invalid adaptor found in job '{job_key}': {adaptor}")

    def process_job_bodies(self, yaml_data, preserved_codes=None):
        """
        Restore preserved code for existing jobs and set default placeholder for new jobs.
        """
        if not preserved_codes:
            preserved_codes = {}
        
        expected_default = "// Add operations here"
        
        if yaml_data and "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            for job_id, job_data in jobs.items():
                if "body" in job_data:
                    body_content = job_data["body"]
                    
                    # If it's already a code placeholder, leave it unchanged
                    if isinstance(body_content, str) and body_content.startswith("__CODE_BLOCK_"):
                        continue
                    
                    # If this job exists in preserved codes, restore the original code
                    elif job_id in preserved_codes:
                        job_data["body"] = preserved_codes[job_id]["code"]
                    
                    # Handle new jobs created by model - set default placeholder
                    else:
                        job_data["body"] = expected_default

    def extract_job_codes(self, yaml_data):
        """
        Extract actual code from job bodies and create placeholder mapping.
        Returns: dict mapping job_id to {code: actual_code, placeholder: unique_id}
        """
        code_mapping = {}
        
        if yaml_data and "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            for job_id, job_data in jobs.items():
                if "body" in job_data:
                    body_content = job_data["body"].strip()
                    # Only preserve if it's actual code (not default placeholder)
                    if body_content and body_content != "// Add operations here":
                        placeholder = self.generate_code_placeholder(job_id)
                        code_mapping[job_id] = {
                            "code": body_content,
                            "placeholder": placeholder
                        }
        
        return code_mapping

    def generate_code_placeholder(self, job_id):
        """Generate unique, deterministic placeholder for job code."""
        return f"__CODE_BLOCK_{job_id}_v1__"

    def replace_codes_with_placeholders(self, yaml_data, code_mapping):
        """Replace actual job bodies with placeholders before sending to model."""
        if yaml_data and "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            for job_id, job_data in jobs.items():
                if job_id in code_mapping and "body" in job_data:
                    job_data["body"] = code_mapping[job_id]["placeholder"]
        
        return yaml.dump(yaml_data, sort_keys=False)

def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        data = Payload.from_dict(data_dict)

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(
            content=data.content, existing_yaml=data.existing_yaml, errors=data.errors, history=data.history
        )

        return {
            "response": result.content,
            "response_yaml": result.content_yaml,
            "history": result.history,
            "usage": result.usage,
        }

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
