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

logger = create_logger("job_chat")

@dataclass
class Payload:
    """
    Data class for validating and storing input parameters.
    Required fields will raise TypeError if not provided.
    """

    content: str
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """
        Create a Payload instance from a dictionary, validating required fields.
        """
        if "content" not in data:
            raise ValueError("'content' is required")

        return cls(content=data["content"], api_key=data.get("api_key"))


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
        self, content: str, history: Optional[List[Dict[str, str]]] = None) -> ChatResponse:
        """
        Generate a response using the Claude API with improved error handling and response processing.
        """
        history = history.copy() if history else []

        system_message, prompt = build_prompt(content, history)

        message = self.client.messages.create(
            max_tokens=self.config.max_tokens, messages=prompt, model=self.config.model, system=system_message
        )

        if hasattr(message, "usage"):
            if message.usage.cache_creation_input_tokens:
                logger.info(f"Cache write: {message.usage.cache_creation_input_tokens} tokens")
            if message.usage.cache_read_input_tokens:
                logger.info(f"Cache read: {message.usage.cache_read_input_tokens} tokens")

        response_parts = []
        for content_block in message.content:
            if content_block.type == "text":
                response_parts.append(content_block.text)
            else:
                logger.warning(f"Unhandled content type: {content_block.type}")

        response = "\n\n".join(response_parts)
        response_text, response_yaml = self.split_format_yaml(response)


        updated_history = history + [
            {"role": "user", "content": content},
            {"role": "assistant", "content": response},
        ]

        return ChatResponse(
            content=response_text,
            content_yaml=response_yaml,
            history=updated_history,
            usage=message.usage.model_dump() if hasattr(message, "usage") else {},
        )

    def split_format_yaml(self, response):
        """Split text and YAML in response and format the YAML."""
        try:
            if "```" in response:
                parts = response.split("```")
                output_text = parts[0].strip()
                output_yaml = parts[1].strip()
                # Decode the escaped newlines into actual newlines
                output_yaml = output_yaml.encode().decode('unicode_escape')
                output_yaml = yaml.safe_load(output_yaml)
                # Convert back to YAML string
                output_yaml = yaml.dump(output_yaml, sort_keys=False)
                return output_text, output_yaml
        except:
            pass
        
        return response.strip(), None

def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        data = Payload.from_dict(data_dict)

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(content=data.content, history=data_dict.get("history", []))

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
