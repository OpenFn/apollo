"""
Workflow Agent - Full implementation based on workflow_chat service.

This agent generates and modifies OpenFn workflows. It can be called standalone
or as a subagent by the supervisor.

Key difference from workflow_chat: workflow_agent does NOT add user/assistant
messages to history when called as a subagent (history management is done by supervisor).
"""
import json
import os
import re
import uuid
import unicodedata
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import yaml
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

# Import utilities from services directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from util import create_logger, ApolloError
from agents.workflow_agent.gen_project_prompt import build_prompt
from agents.workflow_agent.available_adaptors import get_available_adaptors

logger = create_logger("workflow_agent")


@dataclass
class WorkflowAgentPayload:
    """Input payload for workflow agent."""
    content: str                              # Message from supervisor or user
    existing_yaml: Optional[str] = None       # YAML as STRING
    errors: Optional[str] = None
    history: Optional[List[Dict]] = None
    read_only: Optional[bool] = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowAgentPayload":
        """Validate and create Payload from dict."""
        if "content" not in data:
            raise ApolloError(400, "content is required")

        return cls(
            content=data["content"],
            existing_yaml=data.get("existing_yaml"),
            errors=data.get("errors"),
            history=data.get("history"),
            read_only=data.get("read_only", False)
        )


def remove_ids_from_yaml(yaml_str):
    """Remove all 'id' fields from YAML to prevent ID regurgitation in read-only mode."""
    if not yaml_str or not yaml_str.strip():
        return yaml_str
    try:
        yaml_data = yaml.safe_load(yaml_str)

        def remove_ids(obj):
            if isinstance(obj, dict):
                obj.pop("id", None)
                for v in obj.values():
                    remove_ids(v)
            elif isinstance(obj, list):
                for item in obj:
                    remove_ids(item)

        remove_ids(yaml_data)
        return yaml.dump(yaml_data, sort_keys=False, default_flow_style=False)
    except Exception as e:
        logger.warning(f"Could not remove IDs from YAML: {e}")
        return yaml_str


def sanitize_job_names(yaml_data):
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


def validate_adaptors(yaml_data):
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


def extract_and_preserve_components(yaml_data):
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


def restore_components(yaml_data, preserved_values=None):
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


def split_format_yaml(response, preserved_values=None):
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

            with sentry_sdk.start_span(description="validate_adaptors"):
                validate_adaptors(output_yaml)
            with sentry_sdk.start_span(description="sanitize_job_names"):
                sanitize_job_names(output_yaml)
            with sentry_sdk.start_span(description="restore_components"):
                restore_components(output_yaml, preserved_values)
            # Convert back to YAML string with preserved order
            output_yaml = yaml.dump(output_yaml, sort_keys=False)
        else:
            output_yaml = ""

    except Exception as e:
        logger.error(f"Error during JSON parsing: {str(e)}")

    return output_text, output_yaml


def main(data_dict: dict) -> dict:
    """
    Main entry point for workflow agent.

    Generates or modifies OpenFn workflows based on user requests.
    Unlike workflow_chat, this does NOT add user/assistant messages to history
    when called as a subagent (supervisor manages history).

    Args:
        data_dict: Input payload

    Returns:
        Response dictionary with response, response_yaml, history, usage
    """
    try:
        sentry_sdk.set_context("request_data", {
            k: v for k, v in data_dict.items() if k not in ["api_key", "existing_yaml"]
        })

        # Validate payload
        data = WorkflowAgentPayload.from_dict(data_dict)

        logger.info("workflow_agent called")
        logger.info(f"Content: {data.content[:100]}...")
        logger.info(f"Has YAML: {bool(data.existing_yaml)}")
        logger.info(f"Has errors: {bool(data.errors)}")
        logger.info(f"Read-only mode: {data.read_only}")
        logger.info(f"History length: {len(data.history) if data.history else 0}")

        # Initialize Anthropic client
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        client = Anthropic(api_key=api_key)

        # History stays as-is - DO NOT add user message (supervisor manages history)
        history = data.history if data.history else []

        # Process YAML: extract components or remove IDs
        preserved_values = {}
        processed_yaml = data.existing_yaml

        if data.existing_yaml and data.existing_yaml.strip():
            if not data.read_only:
                try:
                    yaml_data = yaml.safe_load(data.existing_yaml)
                    preserved_values, processed_yaml = extract_and_preserve_components(yaml_data)
                except Exception as e:
                    logger.warning(f"Could not parse existing YAML for component extraction: {e}")
            else:
                # In read-only mode, remove IDs to prevent regurgitation
                processed_yaml = remove_ids_from_yaml(data.existing_yaml)

        # Build prompt
        with sentry_sdk.start_span(description="build_prompt"):
            system_message, prompt = build_prompt(
                content=data.content,
                existing_yaml=processed_yaml,
                errors=data.errors,
                history=history,
                read_only=data.read_only
            )

        # Add prefilled opening brace for JSON response
        prompt.append({"role": "assistant", "content": '{\n  "text": "'})

        # Track usage
        accumulated_usage = {
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

        # Retry logic for YAML parsing failures
        max_retries = 1
        for attempt in range(max_retries + 1):
            with sentry_sdk.start_span(description="anthropic_api_call"):
                logger.info("Making non-streaming API call")
                message = client.messages.create(
                    max_tokens=8192,
                    messages=prompt,
                    model="claude-sonnet-4-20250514",
                    system=system_message
                )

            # Track usage from this attempt
            if hasattr(message, "usage"):
                usage = message.usage.model_dump()
                for key in accumulated_usage:
                    if key in usage:
                        accumulated_usage[key] += usage[key]

            # Extract response text
            response_parts = []
            for content_block in message.content:
                if content_block.type == "text":
                    response_parts.append(content_block.text)
                else:
                    logger.warning(f"Unhandled content type: {content_block.type}")

            response = "\n\n".join(response_parts)

            # Add back the prefilled opening brace
            response = '{\n  "text": "' + response

            # Parse and format YAML
            with sentry_sdk.start_span(description="parse_and_format_yaml"):
                response_text, response_yaml = split_format_yaml(response, preserved_values)

            # If YAML parsing succeeded or we're on the last attempt, return the result
            if response_yaml is not None or attempt == max_retries:
                # CRITICAL: Do NOT add user/assistant to history (subagent mode)
                # History stays unchanged - supervisor manages it

                return {
                    "response": response_text,
                    "response_yaml": response_yaml or None,
                    "history": history,  # Unchanged!
                    "usage": accumulated_usage,
                }

            # Otherwise, log and retry
            logger.warning(f"YAML parsing failed, retrying generation (attempt {attempt+1}/{max_retries})")

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
    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in workflow_agent")
        raise ApolloError(500, str(e))
