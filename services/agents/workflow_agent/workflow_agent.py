"""
Workflow Agent - Stub for Phase 1.

This is a placeholder that returns test data. In Phase 2, this will be replaced
with actual workflow generation logic based on workflow_chat service.
"""
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Import utilities from services directory
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from util import create_logger, ApolloError

logger = create_logger(__name__)


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


def main(data_dict: dict) -> dict:
    """
    Phase 1 stub: Returns test data without calling LLM.

    In Phase 2+, this will be replaced with actual workflow generation logic
    based on workflow_chat service.

    Args:
        data_dict: Input payload

    Returns:
        Response dictionary matching workflow_chat structure
    """
    logger.info("workflow_agent called (Phase 1 stub)")

    try:
        # Validate payload
        data = WorkflowAgentPayload.from_dict(data_dict)

        # Log what we received
        logger.info(f"Received message: {data.content[:100]}...")
        logger.info(f"Has YAML: {bool(data.existing_yaml)}")
        logger.info(f"Has errors: {bool(data.errors)}")
        logger.info(f"Read-only mode: {data.read_only}")
        logger.info(f"History length: {len(data.history) if data.history else 0}")

        # Generate stub YAML if none exists
        stub_yaml = data.existing_yaml or """name: example-workflow
workflow:
  steps:
    - id: step-1
      adaptor: "@openfn/language-common@latest"
      expression: "console.log('Hello from workflow_agent stub!')"
"""

        # Return test data matching workflow_chat structure
        return {
            "response": "Testing workflow_agent stub - Phase 1. This is a placeholder response. In Phase 2, I'll generate real workflows based on your request!",
            "response_yaml": stub_yaml,
            "history": (data.history or []) + [
                {"role": "user", "content": data.content},
                {"role": "assistant", "content": "Testing workflow_agent stub - Phase 1"}
            ],
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0
            }
        }

    except ApolloError:
        raise
    except Exception as e:
        logger.exception("Error in workflow_agent stub")
        raise ApolloError(500, str(e))
