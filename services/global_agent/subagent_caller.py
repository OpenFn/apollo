"""
Subagent caller tool for the supervisor agent.

Handles calling subagents and managing message/YAML passing.
"""
import os
import sys
from pathlib import Path
from typing import Dict, Optional

# Import utilities from parent services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from util import create_logger, ApolloError

logger = create_logger(__name__)


def call_workflow_agent(
    tool_input: Dict,
    workflow_yaml: Optional[str] = None
) -> Dict:
    """
    Call the workflow agent and return its results.

    Args:
        tool_input: Tool input from supervisor containing message
        workflow_yaml: Full workflow YAML string

    Returns:
        Dictionary with workflow agent response (raw, not formatted)
    """
    user_message = tool_input.get("message", "")
    if not user_message:
        raise ApolloError(400, "message is required")

    logger.info("Calling workflow_agent")

    workflow_payload = {
        "content": user_message,
        "existing_yaml": workflow_yaml,
        "history": []  # Supervisor includes context in message
    }

    try:
        from workflow_chat.workflow_chat import main as workflow_chat_main
        result = workflow_chat_main(workflow_payload)

        logger.info("workflow_agent completed successfully")

        result["_call_metadata"] = {"subagent": "workflow_agent"}

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling workflow_agent")
        raise ApolloError(500, f"workflow_agent failed: {str(e)}")


def call_job_agent(
    tool_input: Dict,
    workflow_yaml: Optional[str] = None
) -> Dict:
    """
    Call the job code agent and return its results.

    Args:
        tool_input: Tool input from supervisor containing message and optional adaptor
        workflow_yaml: Full workflow YAML string for additional context

    Returns:
        Dictionary with job agent response (raw, not formatted)
    """
    user_message = tool_input.get("message", "")
    if not user_message:
        raise ApolloError(400, "message is required")

    logger.info("Calling job_agent")

    job_context = {}

    # If planner LLM specified an adaptor for this job, inject it into context
    adaptor = tool_input.get("adaptor")
    if adaptor:
        job_context["adaptor"] = adaptor
        logger.info(f"job_agent: using adaptor from tool_input: {adaptor}")

    if workflow_yaml:
        job_context["workflow_yaml"] = workflow_yaml

    job_payload = {
        "content": user_message,
        "context": job_context,
        "suggest_code": True,
        "stream": False,
        "history": []  # Supervisor includes context in message
    }

    try:
        from job_chat.job_chat import main as job_chat_main
        result = job_chat_main(job_payload)

        logger.info("job_agent completed successfully")

        result["_call_metadata"] = {"subagent": "job_agent"}

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling job_agent")
        raise ApolloError(500, f"job_agent failed: {str(e)}")


def format_subagent_result_for_llm(result: Dict) -> str:
    """
    Format subagent result for LLM to read.

    Provides the supervisor with the subagent's response and indicates
    when artifacts (YAML/code) are attached separately.

    Args:
        result: Raw subagent response

    Returns:
        Formatted string for LLM
    """
    metadata = result.get("_call_metadata", {})
    subagent = metadata.get("subagent", "unknown")

    parts = [
        f"Subagent '{subagent}' completed.",
        "",
        result.get('response', 'No response')
    ]

    if subagent == "workflow_agent" and result.get('response_yaml'):
        parts.extend([
            "",
            "Do NOT include workflow YAML in your response - YAML workflow already attached separately for the user."
        ])
    elif subagent == "job_agent" and result.get('suggested_code'):
        parts.extend([
            "",
            "Do NOT include job code in your response - code already attached separately for the user."
        ])

    return "\n".join(parts)
