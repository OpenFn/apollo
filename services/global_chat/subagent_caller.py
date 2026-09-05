"""
Subagent caller tool for the supervisor agent.

Handles calling subagents and managing message/YAML passing.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

# Import utilities from parent services directory
sys.path.append(str(Path(__file__).parent.parent.parent))

from langfuse import observe
from util import create_logger, ApolloError, attachments_to_context, select_attachments
from yaml_utils import find_job_in_yaml

logger = create_logger(__name__)


@observe(name="call_workflow_agent")
def call_workflow_agent(
    tool_input: Dict,
    workflow_yaml: Optional[str] = None,
    attachments: Optional[List[Dict]] = None,
    api_key: Optional[str] = None,
    user: Optional[Dict] = None,
    metrics_opt_in: Optional[bool] = None,
) -> Dict:
    """
    Call the workflow agent and return its results.

    Args:
        tool_input: Tool input from supervisor containing message
        workflow_yaml: Full workflow YAML string
        attachments: This turn's attachments; the planner names which of them
            this call needs, and only those are forwarded

    Returns:
        Dictionary with workflow agent response (raw, not formatted)
    """
    user_message = tool_input.get("message", "")
    if not user_message:
        raise ApolloError(400, "message is required")

    logger.info(f"Calling workflow_agent: {user_message[:120]}")

    selected = select_attachments(attachments, tool_input.get("attachments"))

    workflow_payload = {
        "content": user_message,
        "existing_yaml": workflow_yaml,
        "history": [],  # Supervisor includes context in message
        "stream": False,  # Never stream subagent calls from planner
        "api_key": api_key,
        "meta": {"user": user} if user else None,
        "metrics_opt_in": metrics_opt_in,
        # Same subagent mode the router's direct route uses: no "save and go to
        # the Inspector" scope instruction, and a handover field for requests
        # that belong to the job code agent.
        "subagent": True,
        "attachments": selected,
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
    attachments: Optional[List[Dict]] = None,
    api_key: Optional[str] = None,
    user: Optional[Dict] = None,
    metrics_opt_in: Optional[bool] = None,
) -> Dict:
    """
    Call the job code agent and return its results.

    Args:
        tool_input: Tool input from supervisor containing message and optional adaptor
        workflow_yaml: Full workflow YAML string for additional context
        attachments: This turn's attachments; the planner names which of them
            this call needs, and only those are forwarded

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
        matched_job_key, job_data = find_job_in_yaml(workflow_yaml, job_key)
        if job_data:
            if job_data.get("body"):
                job_context["expression"] = job_data["body"]
                logger.info(f"job_agent: extracted expression from job '{job_key}'")
            if job_data.get("adaptor"):
                job_context["adaptor"] = job_data["adaptor"]
                logger.info(f"job_agent: extracted adaptor '{job_data['adaptor']}' from job '{job_key}'")
            # Tells job_chat's subagent prompt which step is focused/editable
            job_context["job_key"] = matched_job_key

    # Attachments reuse job_chat's own context fields, which already render as
    # <run_logs>/<input>/<output> and never reach the returned history. Only the
    # ones the planner named for this call are forwarded.
    job_context.update(attachments_to_context(select_attachments(attachments, tool_input.get("attachments"))))

    job_payload = {
        "content": user_message,
        "context": job_context,
        "suggest_code": True,
        "stream": False,
        "history": [],  # Supervisor includes context in message
        "api_key": api_key,
        "meta": {"user": user} if user else None,
        "metrics_opt_in": metrics_opt_in,
        # Same subagent mode the router's direct route uses. workflow_yaml must
        # be top-level: Payload.from_dict reads it there, and it is what enables
        # the <workflow_structure> block and the inspect_job_code tool.
        "subagent": True,
        "workflow_yaml": workflow_yaml,
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
    """Return the subagent's prose response for the planner to read.

    A handover is the one case with no prose: in subagent mode a subagent can
    signal that the request belongs elsewhere, and it returns an empty response
    when it does. The router answers a handover by rerouting to the planner —
    but the planner IS that destination, so here it becomes information: the
    reason the step agent couldn't finish, for the planner to act on with its
    other tools.
    """
    if result.get("handover"):
        return (
            f"That agent could not handle this: {result['handover']}. "
            "It is out of scope for that tool — act on it yourself with the right one."
        )
    return result.get("response") or "No response"
