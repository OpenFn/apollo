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
import sentry_sdk
from util import ApolloError, create_logger
from .prompt import build_prompt, build_error_correction_prompt
from .old_prompt import build_old_prompt

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
    suggest_code: Optional[bool] = None

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
            meta=data.get("meta"),
            suggest_code=data.get("suggest_code")
        )


@dataclass
class ChatConfig:
    model: str = "claude-3-7-sonnet-20250219"
    max_tokens: int = 16384
    api_key: Optional[str] = None


@dataclass
class ChatResponse:
    response: str
    suggested_code: Optional[str]
    history: List[Dict[str, str]]
    usage: Dict[str, Any]
    rag: Dict[str, Any]
    diff: Optional[Dict[str, Any]] = None

class AnthropicClient:
    def __init__(self, config: Optional[ChatConfig] = None):
        self.config = config or ChatConfig()
        self.api_key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)

    def generate(
        self, content: str, history: Optional[List[Dict[str, str]]] = None, context: Optional[dict] = None, rag: Optional[str] = None, suggest_code: Optional[bool] = None
    ) -> ChatResponse:
        """
        Generate a response using the Claude API with improved error handling and response processing.
        """
        sentry_sdk.set_tag("prompt_type", "code_suggestions" if suggest_code else "no_code_suggestions")

        with sentry_sdk.start_transaction(name="chat_generation") as transaction:
            history = history.copy() if history else []
            with sentry_sdk.start_span(description="build_prompt"):
                if suggest_code is True:
                    system_message, prompt, retrieved_knowledge = build_prompt(
                        content=content, 
                        history=history, 
                        context=context, 
                        rag=rag, 
                        api_key=self.api_key
                    )
                    prompt.append({"role": "assistant", "content": '{\n  "text_answer": "'}) #TODO

                else:
                    system_message, prompt, retrieved_knowledge = build_old_prompt(
                        content=content, 
                        history=history, 
                        context=context, 
                        rag=rag, 
                        api_key=self.api_key
                        )

            with sentry_sdk.start_span(description="anthropic_api_call"):
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
            if suggest_code is True: #TODO
                response = '{\n  "text_answer": "' + response

            if suggest_code is True:
                # Parse JSON response and apply code edits
                job_code = None
                if context and isinstance(context, dict):
                    job_code = context.get("expression")
                
                with sentry_sdk.start_span(description="parse_and_apply_edits"):
                    text_response, suggested_code, diff = self.parse_and_apply_edits(response=response, content=content, original_code=job_code)
            
            else:
                text_response = response
                suggested_code = None
                diff = None

            updated_history = history + [
                {"role": "user", "content": content},
                {"role": "assistant", "content": text_response},
            ]

            usage = self.sum_usage(
                message.usage.model_dump() if hasattr(message, "usage") else {},
                *[usage_data for usage_key, usage_data in retrieved_knowledge.get("usage", {}).items()]
            )

            return ChatResponse(
                response=text_response,
                suggested_code=suggested_code,
                history=updated_history,
                usage=usage,
                rag=retrieved_knowledge,
                diff=diff
            )

    def parse_and_apply_edits(self, response: str, content: str, original_code: Optional[str] = None) -> tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """Parse JSON response and apply code edits to original code."""
        try:
            response_data = json.loads(response)
            text_answer = response_data.get("text_answer", "").strip()
            code_edits = response_data.get("code_edits", [])
            
            if not code_edits or not original_code:
                return text_answer, None, None
            
            suggested_code, diff = self.apply_code_edits(content=content, text_answer=text_answer, original_code=original_code, code_edits=code_edits)
            return text_answer, suggested_code, diff
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return response, None, None
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return response, None, None

    def apply_code_edits(self, content: str, text_answer: str, original_code: str, code_edits: List[Dict[str, Any]]) -> tuple[Optional[str], Dict[str, Any]]:
        """Apply a list of code edits to the original code."""
        current_code = original_code
        total_changes = len(code_edits)
        patches_applied = 0
        warnings = []
        
        for edit in code_edits:
            try:
                new_code, edit_applied, warning = self.apply_single_edit(content=content, text_answer=text_answer, code=current_code, edit=edit)
                if new_code is not None:
                    current_code = new_code
                if edit_applied:
                    patches_applied += 1
                if warning:
                    warnings.append(warning)
            except Exception as e:
                logger.warning(f"Failed to apply edit {edit}: {e}")
                warnings.append(f"Failed to apply edit: {str(e)}")
        
        diff = {
            "patches_applied": patches_applied
        }
        
        if warnings:
            diff["warning"] = ". ".join(warnings)
        
        final_code = current_code if patches_applied > 0 else None
        return final_code, diff

    def apply_single_edit(self, content: str, text_answer: str, code: str, edit: Dict[str, Any]) -> tuple[str, bool, Optional[str]]:
        """Apply a single code edit and return (new_code, success, warning)."""

        sentry_sdk.set_context("code_edit_context", {
            "llm_text_answer": text_answer,
            "llm_edit_answe": edit,
        })

        action = edit.get("action")
        
        if action == "replace":
            old_code = edit.get("old_code")
            new_code = edit.get("new_code")
            logger.info(f"attempting this edit: old code: {old_code}\nnew code: {new_code}")
            
            if not old_code or new_code is None:
                msg = "Code edit failed: Replace action requires old_code and new_code"         
            elif old_code not in code:
                msg = "Code edit failed: old_code not found in current code"
            elif code.count(old_code) > 1:
                msg = "Code edit failed: multiple matches"
            else:
                return code.replace(old_code, new_code), True, None

            if msg:
                sentry_sdk.capture_message(msg, level="warning")
                return self.handle_replace_error(content, text_answer, code, edit, msg)
        
        elif action == "rewrite":
            new_code = edit.get("new_code")
            if not new_code:
                warning = "Rewrite code failed, new code missing"
                logger.warning(warning)
                return None, False, warning
            return new_code, True, None
        
        else:
            warning ="Error in applying code edit, invalid action"
            logger.warning(warning)
            return None, False, warning
        
    def handle_replace_error(self, content: str, text_answer: str, code: str, edit: Dict[str, Any], error_message: str) -> tuple[str, bool, str]:
        """Helper to handle replace action errors with correction attempt."""
        old_code = edit.get("old_code")
        new_code = edit.get("new_code")
        corrected_code, success, correction_warning = self.try_error_correction(
            content=content, error_message=error_message, old_code=old_code, 
            new_code=new_code, full_code=code, text_explanation=text_answer
        )

        warning = "Initial error: " + error_message + (f". Correction warning: {correction_warning}" if correction_warning else "")

        if not success:
            sentry_sdk.capture_message(warning, level="error")

        return (corrected_code, success, warning)
        
    def try_error_correction(self, content: str, error_message: str, old_code: str, new_code: str, full_code: str, text_explanation: str) -> tuple[str, bool, Optional[str]]:
        """Try to correct the edit once, return (code, success)."""
        logger.info(f"Code edit error: {error_message}. Attempting correction...")
        
        try:
            system_message, prompt = build_error_correction_prompt(
                content=content,
                error_message=error_message,
                old_code=old_code,
                new_code=new_code,
                full_code=full_code,
                text_explanation=text_explanation
            )
            prompt.append({"role": "assistant", "content": '{\n  "explanation": "'}) #TODO
            message = self.client.messages.create(
                max_tokens=16384,
                messages=prompt,
                model=self.config.model,
                system=system_message
            )
            
            response = "\n\n".join([block.text for block in message.content if block.type == "text"])
            response = '{\n  "explanation": "' + response  # Add back the prefilled opening brace #TODO
            correction_data = json.loads(response)

            corrected_old = correction_data.get("corrected_old_code")
            corrected_new = correction_data.get("corrected_new_code")
            logger.info(f"Corrector response: {response}")
            
            if corrected_old and corrected_new is not None and corrected_old in full_code:
                warning = None
                if full_code.count(corrected_old) > 1:
                    warning = "Corrected old code appears more than once in the code. Applying edit to first occurrence only."
                    logger.warning(warning)
                logger.info("Successfully applied corrected edit")
                return full_code.replace(corrected_old, corrected_new, 1), True, warning

        except Exception as e:
            warning = f"Error correction failed: {e}"
            logger.warning(warning)
            return None, False, warning
        
        warning = f"Error correction failed. Tried to apply: {correction_data.get('corrected_new_code')}"
        logger.warning(warning)
        return None, False, warning

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
        sentry_sdk.set_context("request_data", {
            k: v for k, v in data_dict.items() if k != "api_key"
            })

        data = Payload.from_dict(data_dict)

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(
            content=data.content, 
            history=data_dict.get("history", []), 
            context=data.context, 
            rag=data_dict.get("meta", {}).get("rag"),
            suggest_code=data.suggest_code
        )

        response_dict = {
            "response": result.response,
            "suggested_code": result.suggested_code,
            "history": result.history, 
            "usage": result.usage, 
            "meta": {"rag": result.rag}
        }

        if result.diff:
            response_dict["diff"] = result.diff
        
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