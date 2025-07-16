import os
import json
from typing import List, Optional, Dict, Any
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
from .prompt import build_prompt

logger = create_logger("job_chat")


@dataclass
class Payload:
    """
    Data class for validating and storing input parameters.
    Required fields will raise TypeError if not provided.
    """

    content: str
    context: Optional[dict] = None
    api_key: Optional[str] = None
    meta: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """
        Create a Payload instance from a dictionary, validating required fields.
        """
        if "content" not in data:
            raise ValueError("'content' is required")

        return cls(
            content=data["content"], 
            context=data.get("context"), 
            api_key=data.get("api_key"), 
            meta=data.get("meta")
        )


@dataclass
class ChatConfig:
    model: str = "claude-3-7-sonnet-20250219"
    max_tokens: int = 16384
    api_key: Optional[str] = None


@dataclass
class ChatResponse:
    content: dict  # Now a dict with 'response' and 'suggested_code'
    history: List[Dict[str, str]]
    usage: Dict[str, Any]
    rag: Dict[str, Any]

class AnthropicClient:
    def __init__(self, config: Optional[ChatConfig] = None):
        self.config = config or ChatConfig()
        self.api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)

    def generate(
        self, content: str, history: Optional[List[Dict[str, str]]] = None, context: Optional[dict] = None, rag: Optional[str] = None
    ) -> ChatResponse:
        """
        Generate a response using the Claude API with improved error handling and response processing.
        """
        history = history.copy() if history else []

        system_message, prompt, retrieved_knowledge = build_prompt(
            content=content, 
            history=history, 
            context=context, 
            rag=rag, 
            api_key=self.api_key
            )

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

        # Parse JSON response and apply code edits
        job_code = None
        if context and isinstance(context, dict):
            job_code = context.get("expression")
        text_response, suggested_code = self.parse_and_apply_edits(response, job_code)

        updated_history = history + [
            {"role": "user", "content": content},
            {"role": "assistant", "content": text_response},
        ]

        usage = self.sum_usage(
            message.usage.model_dump() if hasattr(message, "usage") else {},
            *[usage_data for usage_key, usage_data in retrieved_knowledge.get("usage", {}).items()]
        )

        # New: content is a dict with 'response' and 'suggested_code'
        content_dict = {"response": text_response, "suggested_code": suggested_code}

        return ChatResponse(
            content=content_dict,
            history=updated_history,
            usage=usage,
            rag=retrieved_knowledge
        )

    def parse_and_apply_edits(self, response: str, original_code: Optional[str] = None) -> tuple[str, Optional[str]]:
        """Parse JSON response and apply code edits to original code."""
        try:
            response_data = json.loads(response)
            text_answer = response_data.get("text_answer", "").strip()
            code_edits = response_data.get("code_edits", [])
            
            if not code_edits or not original_code:
                return text_answer, None
            
            suggested_code = self.apply_code_edits(original_code, code_edits)
            return text_answer, suggested_code
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return response, None
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return response, None

    def apply_code_edits(self, original_code: str, code_edits: List[Dict[str, Any]]) -> str:
        """Apply a list of code edits to the original code."""
        current_code = original_code
        
        for edit in code_edits:
            try:
                current_code = self.apply_single_edit(current_code, edit)
            except Exception as e:
                logger.warning(f"Failed to apply edit {edit}: {e}")
                # Continue with other edits even if one fails
        
        return current_code

    def apply_single_edit(self, code: str, edit: Dict[str, Any]) -> str:
        """Apply a single code edit."""
        action = edit.get("action")
        
        if action == "replace":
            old_code = edit.get("old_code")
            new_code = edit.get("new_code")
            
            if not old_code or new_code is None:
                logger.error("Replace action requires old_code and new_code")
            
            if old_code not in code:
                logger.error(f"old_code not found in current code")
            
            if code.count(old_code) > 1:
                logger.error(f"old_code matches multiple locations")
            
            return code.replace(old_code, new_code)
        
        elif action == "rewrite":
            new_code = edit.get("new_code")
            if not new_code:
                logger.error("Rewrite action requires new_code")
            
            return new_code
        
        else:
            raise ValueError(f"Unknown action: {action}")

    def sum_usage(self, *usage_objects):
        """Sum multiple Usage object token counts and return a count dictionary."""
        result = {}
        
        for usage in usage_objects:
            for field in ["cache_creation_input_tokens", "cache_read_input_tokens", "input_tokens", "output_tokens"]:
                value = usage.get(field)
                if value is not None:
                    result[field] = result.get(field, 0) + value
        
        return result



def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        data = Payload.from_dict(data_dict)

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(
            content=data.content, 
            history=data_dict.get("history", []), 
            context=data.context, 
            rag=data_dict.get("meta", {}).get("rag")
        )

        response_dict = {
            "response": result.content, 
            "history": result.history, 
            "usage": result.usage, 
            "meta": {"rag": result.rag}
        }
        
        return response_dict

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
