"""
Subagent caller tool for the supervisor agent.

Handles calling subagents and managing message/YAML passing.
"""
import sys
from pathlib import Path
from typing import Dict, Optional

# Import utilities from parent services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from langfuse import observe
from util import create_logger, ApolloError
from global_chat.yaml_utils import find_job_in_yaml

logger = create_logger(__name__)


@observe(name="call_workflow_agent")
def call_workflow_agent(
    tool_input: Dict,
    workflow_yaml: Optional[str] = None,
    api_key: Optional[str] = None
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

    logger.info(f"Calling workflow_agent: {user_message[:120]}")

    workflow_payload = {
        "content": user_message,
        "existing_yaml": workflow_yaml,
        "history": [],  # Supervisor includes context in message
        "api_key": api_key
    }

    try:
        from workflow_chat.workflow_chat import main as workflow_chat_main
        result = workflow_chat_main(workflow_payload)

        response_preview = result.get("response", "")[:120]
        logger.info(f"workflow_agent response: {response_preview}")

        result["_call_metadata"] = {"subagent": "workflow_agent"}

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling workflow_agent")
        raise ApolloError(500, f"workflow_agent failed: {str(e)}")


@observe(name="call_job_agent")
def call_job_agent(
    tool_input: Dict,
    workflow_yaml: Optional[str] = None,
    api_key: Optional[str] = None
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

    job_context = {}

    job_key = tool_input.get("job_key")
    logger.info(f"Calling job_agent (job_key={job_key}): {user_message[:120]}")
    if job_key and workflow_yaml:
        _, job_data = find_job_in_yaml(workflow_yaml, job_key)
        if job_data:
            if job_data.get("body"):
                job_context["expression"] = job_data["body"]
                logger.info(f"job_agent: extracted expression from job '{job_key}'")
            if job_data.get("adaptor"):
                job_context["adaptor"] = job_data["adaptor"]
                logger.info(f"job_agent: extracted adaptor '{job_data['adaptor']}' from job '{job_key}'")
    elif workflow_yaml:
        job_context["workflow_yaml"] = workflow_yaml

    job_payload = {
        "content": user_message,
        "context": job_context,
        "suggest_code": True,
        "stream": False,
        "history": [],  # Supervisor includes context in message
        "api_key": api_key
    }

    try:
        from job_chat.job_chat import main as job_chat_main
        result = job_chat_main(job_payload)

        response_preview = result.get("response", "")[:120]
        logger.info(f"job_agent response: {response_preview}")

        result["_call_metadata"] = {"subagent": "job_agent", "job_key": job_key}

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error calling job_agent")
        raise ApolloError(500, f"job_agent failed: {str(e)}")


def format_subagent_result_for_llm(result: Dict) -> str:
    """Return the subagent's prose response for the planner to read."""
    return result.get('response', 'No response')
