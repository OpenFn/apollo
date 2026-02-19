"""
Global Agent - Main entry point.

This is the supervisor agent that coordinates subagents and tools.
"""
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Import utilities from parent services directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from util import ApolloError, create_logger
from global_agent.config_loader import ConfigLoader
from global_agent.router import RouterAgent

logger = create_logger(__name__)


@dataclass
class Payload:
    """Input payload for global agent."""
    content: str
    context: Optional[Dict] = None
    history: Optional[List[Dict]] = None
    api_key: Optional[str] = None
    stream: Optional[bool] = False
    read_only: Optional[bool] = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """Validate and create Payload from dict."""
        if "content" not in data:
            raise ApolloError(400, "content is required")

        return cls(
            content=data["content"],
            context=data.get("context"),
            history=data.get("history"),
            api_key=data.get("api_key"),
            stream=data.get("stream", False),
            read_only=data.get("read_only", False)
        )

    def get_workflow_yaml(self) -> Optional[str]:
        """Extract workflow_yaml from context."""
        return self.context.get("workflow_yaml") if self.context else None

    def get_errors(self) -> Optional[str]:
        """Extract errors from context."""
        return self.context.get("errors") if self.context else None

    def get_job_code_context(self) -> Optional[Dict]:
        """Extract job_code from context."""
        return self.context.get("job_code") if self.context else None


def main(data_dict: dict) -> dict:
    """
    Main entry point for global agent service.

    Args:
        data_dict: Input payload as dictionary

    Returns:
        Response dictionary with text, YAML, history, usage, meta
    """
    try:
        # 1. Validate payload
        data = Payload.from_dict(data_dict)
        logger.info(f"Global agent called with content: {data.content[:100]}...")

        # 2. Load configuration
        config_loader = ConfigLoader("config.yaml")

        # 3. Initialize router
        router = RouterAgent(config_loader, data.api_key)

        # 4. Route and execute
        result = router.route_and_execute(
            content=data.content,
            workflow_yaml=data.get_workflow_yaml(),
            errors=data.get_errors(),
            job_code_context=data.get_job_code_context(),
            history=data.history or [],
            read_only=data.read_only,
            stream=data.stream
        )

        # 5. Return structured response with attachments
        return {
            "response": result.response,
            "attachments": [{"type": a.type, "content": a.content} for a in result.attachments],
            "history": result.history,
            "usage": result.usage,
            "meta": result.meta
        }

    except ApolloError as e:
        logger.error(f"ApolloError in global_agent: {e}")
        raise e
    except Exception as e:
        logger.exception("Unexpected error in global_agent")
        raise ApolloError(500, str(e))
