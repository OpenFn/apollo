import json
import os
import re
import uuid
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
import sentry_sdk
from util import ApolloError, create_logger
from .gen_project_prompt import build_prompt
from workflow_chat.available_adaptors import get_available_adaptors
from streaming_util import StreamManager

logger = create_logger("workflow_chat")


# Helper function for page navigation
def add_page_prefix(content: str, page: Optional[dict]) -> str:
    """Add [pg:...] prefix to message."""
    if not page:
        return content

    prefix_parts = []
    if page.get('type'):
        prefix_parts.append(str(page['type']))
    if page.get('name'):
        prefix_parts.append(str(page['name']))
    if page.get('adaptor'):
        prefix_parts.append(str(page['adaptor']))

    if not prefix_parts:
        return content

    prefix = f"[pg:{'/'.join(prefix_parts)}]"
    return f"{prefix} {content}"


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
    context: Optional[dict] = None
    api_key: Optional[str] = None
    stream: Optional[bool] = False

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
            context=data.get("context"),
            api_key=data.get("api_key"),
            stream=data.get("stream", False)
        )


@dataclass
class ChatConfig:
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 8192
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
        stream: Optional[bool] = False,
        current_page: Optional[dict] = None,
    ) -> ChatResponse:
        """Generate a response using the Claude API. Retry up to 2 times if YAML/JSON parsing fails."""
        
        with sentry_sdk.start_transaction(name="workflow_generation") as transaction:
            history = history.copy() if history else []

            stream_manager = StreamManager(model=self.config.model, stream=stream)
            
            # Extract and preserve existing components
            preserved_values = {}
            processed_existing_yaml = existing_yaml
            
            if existing_yaml and existing_yaml.strip():
                try:
                    yaml_data = yaml.safe_load(existing_yaml)
                    preserved_values, processed_existing_yaml = self.extract_and_preserve_components(yaml_data)
                except Exception as e:
                    logger.warning(f"Could not parse existing YAML for component extraction: {e}")
            
            with sentry_sdk.start_span(description="build_prompt"):
                system_message, prompt = build_prompt(
                    content=content,
                    existing_yaml=processed_existing_yaml,
                    errors=errors,
                    history=history
                )

            # Add prefilled opening brace for JSON response
            prompt.append({"role": "assistant", "content": '{\n  "text": "'})

            accumulated_usage = {
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

            max_retries = 1
            for attempt in range(max_retries + 1):
                with sentry_sdk.start_span(description="anthropic_api_call"):
                    if stream:
                        logger.info("Making streaming API call")
                        stream_manager.send_thinking("Thinking...")

                        text_complete = False
                        sent_length = 0
                        accumulated_response = ""

                        with self.client.messages.stream(
                            max_tokens=self.config.max_tokens,
                            messages=prompt,
                            model=self.config.model,
                            system=system_message
                        ) as stream_obj:
                            for event in stream_obj:
                                accumulated_response, text_complete, sent_length = self.process_stream_event(
                                    event,
                                    accumulated_response,
                                    text_complete,
                                    sent_length,
                                    stream_manager
                                )
                        message = stream_obj.get_final_message()

                        # Flush any remaining buffered content
                        if not text_complete:
                            if sent_length < len(accumulated_response):
                                remaining = accumulated_response[sent_length:]
                                stream_manager.send_text(remaining)

                    else:
                        logger.info("Making non-streaming API call")
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

                # Add back the prefilled opening brace
                response = '{\n  "text": "' + response

                with sentry_sdk.start_span(description="parse_and_format_yaml"):

                    response_text, response_yaml = self.split_format_yaml(response, preserved_values, stream_manager)

                # If YAML parsing succeeded or we're on the last attempt, return the result
                if response_yaml is not None or attempt == max_retries:
                    # Add prefix to content when building history
                    prefixed_content = add_page_prefix(content, current_page)

                    updated_history = history + [
                        {"role": "user", "content": prefixed_content},
                        {"role": "assistant", "content": response},
                    ]

                    stream_manager.end_stream()

                    return ChatResponse(
                        content=response_text,
                        content_yaml=response_yaml or None,
                        history=updated_history,
                        usage=accumulated_usage,
                    )

                # Otherwise, log and retry
                logger.warning(f"YAML parsing failed, retrying generation (attempt {attempt+1}/{max_retries})")

    def sanitize_job_names(self, yaml_data):
        """
        Sanitize job names by removing special characters and normalizing diacritics.
        Also sanitizes job references in edges (source and target fields) and edge keys.
        """
        if not yaml_data:
            return
            
        def sanitize_single_name(name):
            if not name or not isinstance(name, str):
                return name
            # Normalize unicode characters (removes diacritics)
            normalized = unicodedata.normalize('NFKD', name)
            ascii_name = normalized.encode('ascii', 'ignore').decode('ascii')
            # Keep only alphanumeric, spaces, hyphens, and underscores
            return re.sub(r'[^a-zA-Z0-9\s\-_]', '', ascii_name)
        
        if "jobs" in yaml_data:
            jobs = yaml_data["jobs"]
            name_mapping = {}
            
            for job_key, job_data in jobs.items():
                if "name" in job_data:
                    original_name = str(job_data["name"])
                    sanitized_name = sanitize_single_name(original_name)
                    
                    job_data["name"] = sanitized_name
                    name_mapping[original_name] = sanitized_name
                    
                    if original_name != sanitized_name:
                        logger.info(f"Sanitized job name: '{original_name}' -> '{sanitized_name}'")
        
        if "edges" in yaml_data:
            sanitized_edges = {}
            
            for edge_key, edge_data in yaml_data["edges"].items():
                if "source_job" in edge_data:
                    original_source = str(edge_data["source_job"])
                    edge_data["source_job"] = sanitize_single_name(original_source)
                    if original_source != edge_data["source_job"]:
                        logger.info(f"Sanitized edge source_job: '{original_source}' -> '{edge_data['source_job']}'")
                
                if "target_job" in edge_data:
                    original_target = str(edge_data["target_job"])
                    edge_data["target_job"] = sanitize_single_name(original_target)
                    if original_target != edge_data["target_job"]:
                        logger.info(f"Sanitized edge target_job: '{original_target}' -> '{edge_data['target_job']}'")
                
                if "->" in edge_key:
                    source_part, target_part = edge_key.split("->", 1)
                    sanitized_source = sanitize_single_name(source_part)
                    sanitized_target = sanitize_single_name(target_part)
                    sanitized_edge_key = f"{sanitized_source}->{sanitized_target}"
                    
                    if sanitized_edge_key != edge_key:
                        logger.info(f"Sanitized edge key: '{edge_key}' -> '{sanitized_edge_key}'")
                    
                    sanitized_edges[sanitized_edge_key] = edge_data
                else:
                    # If there's no arrow, just keep the original key
                    sanitized_edges[edge_key] = edge_data
            
            yaml_data["edges"] = sanitized_edges

    def split_format_yaml(self, response, preserved_values=None, stream_manager=None):
        """Split text and YAML in response and format the YAML."""
        output_text, output_yaml = "", None

        try:
            # Try to parse the response as JSON
            response_data = json.loads(response)

            # Extract text and yaml from the JSON
            output_text = response_data.get("text", "").strip()
            output_yaml = response_data.get("yaml", "")

            if output_yaml and output_yaml.strip():
                if stream_manager:
                    stream_manager.send_thinking("Formatting workflow...", signature="proxy_formatting_signature")
                # Parse YAML string into Python object
                output_yaml = yaml.safe_load(output_yaml)

                with sentry_sdk.start_span(description="validate_adaptors"):
                    self.validate_adaptors(output_yaml)
                with sentry_sdk.start_span(description="sanitize_job_names"):
                    self.sanitize_job_names(output_yaml)
                with sentry_sdk.start_span(description="restore_components"):
                    self.restore_components(output_yaml, preserved_values)
                # Convert back to YAML string with preserved order
                output_yaml = yaml.dump(output_yaml, sort_keys=False)
            else:
                output_yaml = ""
                
        except Exception as e:
            logger.error(f"Error during JSON parsing: {str(e)}")

        return output_text, output_yaml

    def validate_adaptors(self, yaml_data):
        """Validate that all adaptors in the YAML are on the approved list (name only, ignore version)."""

        try:
            available_adaptors = get_available_adaptors()
            valid_adaptor_names = {adaptor["name"] for adaptor in available_adaptors}

            if yaml_data and "jobs" in yaml_data:
                jobs = yaml_data["jobs"]
                for job_key, job_data in jobs.items():
                    if "adaptor" in job_data:
                        adaptor = job_data["adaptor"]
                        # Remove version if present (after last @)
                        base = adaptor.rsplit("@", 1)[0]
                        # Always remove '@openfn/language-' prefix
                        short_name = base[len("@openfn/language-"):]
                        if short_name not in valid_adaptor_names:
                            logger.warning(f"Invalid adaptor found in job '{job_key}': {adaptor}")
        except Exception as e:
            logger.error(f"validate_adaptors encountered an error: {e}")

    def extract_and_preserve_components(self, yaml_data):
        """
        Extract both codes and IDs from all components.
        Returns: (preserved_values, processed_yaml_string)
        """
        if not yaml_data:
            return {}, None
        
        preserved_values = {}
        
        if "jobs" in yaml_data:
            for job_key, job_data in yaml_data["jobs"].items():
                if "body" in job_data:
                    body_content = job_data["body"].strip()
                    if body_content and body_content != "// Add operations here":
                        placeholder = f"__CODE_BLOCK_{job_key}__"
                        preserved_values[placeholder] = body_content
                        job_data["body"] = placeholder
                
                if "id" in job_data:
                    placeholder = f"__ID_JOB_{job_key}__"
                    preserved_values[placeholder] = job_data["id"]
                    job_data["id"] = placeholder
        
        if "triggers" in yaml_data:
            for trigger_key, trigger_data in yaml_data["triggers"].items():
                if "id" in trigger_data:
                    # Store the trigger ID directly without placeholder
                    preserved_values["trigger_id"] = trigger_data["id"]
                    # Remove the id key from what we send to the model
                    del trigger_data["id"]
        
        if "edges" in yaml_data:
            for edge_key, edge_data in yaml_data["edges"].items():
                if "id" in edge_data:
                    placeholder = f"__ID_EDGE_{edge_key}__"
                    preserved_values[placeholder] = edge_data["id"]
                    edge_data["id"] = placeholder
        
        return preserved_values, yaml.dump(yaml_data, sort_keys=False)

    def restore_components(self, yaml_data, preserved_values=None):
        """
        Restore preserved codes and IDs, generate new UUIDs for new components.
        """
        if not yaml_data:
            return
        
        preserved_values = preserved_values or {}
        
        if "jobs" in yaml_data:
            for job_key, job_data in yaml_data["jobs"].items():
                if "body" in job_data:
                    current_body = job_data["body"]
                    if isinstance(current_body, str) and current_body in preserved_values:
                        job_data["body"] = preserved_values[current_body]
                    else:
                        job_data["body"] = "// Add operations here"
                else:
                    job_data["body"] = "// Add operations here"
                
                if "id" in job_data:
                    current_id = job_data["id"]
                    
                    if isinstance(current_id, str) and current_id in preserved_values:
                        job_data["id"] = preserved_values[current_id]
                    elif isinstance(current_id, str) and current_id.startswith("__ID_") and current_id.endswith("__"):
                        msg = f"Unknown placeholder {current_id}, generating new ID"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        job_data["id"] = str(uuid.uuid4())
                else:
                    job_data["id"] = str(uuid.uuid4())
        
        if "triggers" in yaml_data:
            for trigger_key, trigger_data in yaml_data["triggers"].items():
                if "trigger_id" in preserved_values:
                    # Directly restore the preserved trigger ID
                    trigger_data["id"] = preserved_values["trigger_id"]
                elif "id" not in trigger_data:
                    # Generate new ID if no preserved ID exists
                    trigger_data["id"] = str(uuid.uuid4())

        if "edges" in yaml_data:
            for edge_key, edge_data in yaml_data["edges"].items():
                if "id" in edge_data:
                    current_id = edge_data["id"]
                    
                    if isinstance(current_id, str) and current_id in preserved_values:
                        edge_data["id"] = preserved_values[current_id]
                    elif isinstance(current_id, str) and current_id.startswith("__ID_") and current_id.endswith("__"):
                        msg = f"Unknown placeholder {current_id}, generating new ID"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        edge_data["id"] = str(uuid.uuid4())
                else:
                    edge_data["id"] = str(uuid.uuid4())

    def process_stream_event(self, event, accumulated_response, text_complete, sent_length, stream_manager):
        """
        Process a single stream event from the Anthropic API.
        """
        if event.type == "content_block_delta":
            if event.delta.type == "text_delta":
                text_chunk = event.delta.text
                accumulated_response += text_chunk

                if not text_complete:
                    delimiter = '",\n  "yaml":'

                    # Stream chunks until we hit the YAML part
                    if delimiter in accumulated_response:
                        # Get only the text part and send any remaining unsent text
                        text_only = accumulated_response.split(delimiter)[0]
                        remaining_text = text_only[sent_length:]
                        if remaining_text:
                            stream_manager.send_text(remaining_text)

                        text_complete = True
                    else:
                        # Buffer to avoid sending partial delimiter
                        # Only send content that we know won't be part of the delimiter
                        buffer_size = len(delimiter) - 1
                        safe_to_send_until = len(accumulated_response) - buffer_size

                        if safe_to_send_until > sent_length:
                            safe_text = accumulated_response[sent_length:safe_to_send_until]
                            stream_manager.send_text(safe_text)
                            sent_length = safe_to_send_until
        return accumulated_response, text_complete, sent_length


def main(data_dict: dict) -> dict:
    """
    Main entry point with improved error handling and input validation.
    """
    try:
        sentry_sdk.set_context("request_data", {
            k: v for k, v in data_dict.items() if k != "api_key"
            })

        data = Payload.from_dict(data_dict)

        # Construct current_page from context
        current_page = None
        if data.context:
            page_name = data.context.get("page_name")

            # Only construct page if we have page_name
            if page_name:
                current_page = {
                    "type": "workflow",
                    "name": page_name
                }

        config = ChatConfig(api_key=data.api_key) if data.api_key else None
        client = AnthropicClient(config)

        result = client.generate(
            content=data.content,
            existing_yaml=data.existing_yaml,
            errors=data.errors,
            history=data.history,
            stream=data.stream,
            current_page=current_page
        )

        # Build response with meta
        response_dict = {
            "response": result.content,
            "response_yaml": result.content_yaml,
            "history": result.history,
            "usage": result.usage
        }

        # Only add meta with last_page if we have current_page
        if current_page:
            response_dict["meta"] = {
                "last_page": current_page
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