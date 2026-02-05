"""
Subagent caller tool for the supervisor agent.

Handles calling subagents and managing message/YAML passing.
"""
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Import utilities from parent services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from util import create_logger, ApolloError

logger = create_logger(__name__)


def call_workflow_agent(
    tool_input: Dict,
    existing_yaml: Optional[str],
    errors: Optional[str],
    history: List[Dict],
    read_only: bool
) -> Dict:
    """
    Call the workflow agent and return its results.

    CRITICAL: YAML is passed as-is, never parsed or modified.

    Args:
        tool_input: Tool input from supervisor containing mode, message
        existing_yaml: YAML workflow as STRING (never parsed)
        errors: Error context
        history: Conversation history
        read_only: Read-only mode flag

    Returns:
        Dictionary with workflow agent response (raw, not formatted)
    """
    mode = tool_input.get("mode")

    if not mode:
        raise ApolloError(400, "mode is required")

    logger.info(f"Calling workflow_agent (mode: {mode})")

    # Determine message to send
    if mode == "pass_through":
        # Get the original user message from history
        user_message = _get_original_user_message(history)
    elif mode == "custom_message":
        user_message = tool_input.get("message", "")
        if not user_message:
            raise ApolloError(400, "custom_message mode requires 'message' field")
    else:
        raise ApolloError(400, f"Invalid mode: {mode}")

    # Build workflow agent payload
    workflow_payload = {
        "content": user_message,
        "existing_yaml": existing_yaml,  # PASS AS STRING - DO NOT PARSE
        "errors": errors,
        "history": history,
        "read_only": read_only
    }

    # Call workflow agent 
    try:
        from workflow_chat.workflow_chat import main as workflow_chat_main
        result = workflow_chat_main(workflow_payload)

        logger.info("workflow_agent completed successfully")

        # Add metadata about the call
        result["_call_metadata"] = {
            "subagent": "workflow_agent",
            "mode": mode
        }

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling workflow_agent")
        raise ApolloError(500, f"workflow_agent failed: {str(e)}")


def call_job_agent(
    tool_input: Dict,
    history: List[Dict]
) -> Dict:
    """
    Call the job code agent and return its results.

    Args:
        tool_input: Tool input from supervisor containing mode, message
        history: Conversation history

    Returns:
        Dictionary with job agent response (raw, not formatted)
    """
    mode = tool_input.get("mode")

    if not mode:
        raise ApolloError(400, "mode is required")

    logger.info(f"Calling job_agent (mode: {mode})")

    # Determine message to send
    if mode == "pass_through":
        # Get the original user message from history
        user_message = _get_original_user_message(history)
    elif mode == "custom_message":
        user_message = tool_input.get("message", "")
        if not user_message:
            raise ApolloError(400, "custom_message mode requires 'message' field")
    else:
        raise ApolloError(400, f"Invalid mode: {mode}")

    # Build job agent payload
    job_payload = {
        "content": user_message,
        "context": {},
        "suggest_code": True,
        "stream": False,
        "history": history
    }

    # Call job agent
    try:
        from job_chat.job_chat import main as job_chat_main
        result = job_chat_main(job_payload)

        logger.info("job_agent completed successfully")

        # Add metadata about the call
        result["_call_metadata"] = {
            "subagent": "job_agent",
            "mode": mode
        }

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling job_agent")
        raise ApolloError(500, f"job_agent failed: {str(e)}")


def format_subagent_result_for_llm(result: Dict) -> str:
    """
    Format subagent result for LLM to read.

    Allows the supervisor to synthesize the subagent response in its own words.

    Args:
        result: Raw subagent response

    Returns:
        Formatted string for LLM
    """
    metadata = result.get("_call_metadata", {})
    subagent = metadata.get("subagent", "unknown")

    # Handle different subagent types
    if subagent == "workflow_agent":
        if result.get('response_yaml'):
            output_info = "YAML: Attached separately"
            reminder = "CRITICAL: Do NOT include YAML in your text response - it's already attached."
        else:
            output_info = "YAML: Not generated (agent provided clarification/explanation)"
            reminder = ""
    elif subagent == "job_agent":
        if result.get('suggested_code'):
            output_info = "Job Code: Attached separately"
            reminder = "CRITICAL: Do NOT include job code in your text response - it's already attached."
        else:
            output_info = "Job Code: Not generated (agent provided clarification/explanation)"
            reminder = ""
    else:
        output_info = "Output: Unknown"
        reminder = ""

    formatted = f"""Subagent '{subagent}' completed successfully.

Response: {result.get('response', 'No response')}

{output_info}

Token Usage: {result.get('usage', {}).get('input_tokens', 0)} input, {result.get('usage', {}).get('output_tokens', 0)} output tokens

You should now synthesize this information into your response to the user.
{reminder}"""

    return formatted


def _get_original_user_message(history: List[Dict]) -> str:
    """
    Extract the most recent user message from history.

    Args:
        history: Conversation history

    Returns:
        The user's message
    """
    if not history:
        raise ApolloError(400, "Cannot use pass_through mode without history")

    # Find most recent user message
    for message in reversed(history):
        if message.get("role") == "user":
            return message.get("content", "")

    raise ApolloError(400, "No user message found in history")
