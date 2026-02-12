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
    content: str                              # User message (required)
    existing_yaml: Optional[str] = None       # YAML as STRING
    errors: Optional[str] = None              # Error context
    context: Optional[Dict] = None            # Job code context
    history: Optional[List[Dict]] = None      # Chat history
    api_key: Optional[str] = None             # Override API key
    stream: Optional[bool] = False            # Streaming flag (not implemented yet)
    read_only: Optional[bool] = False         # Read-only mode

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """Validate and create Payload from dict."""
        if "content" not in data:
            raise ApolloError(400, "content is required")

        return cls(
            content=data["content"],
            existing_yaml=data.get("existing_yaml"),
            errors=data.get("errors"),
            context=data.get("context"),
            history=data.get("history"),
            api_key=data.get("api_key"),
            stream=data.get("stream", False),
            read_only=data.get("read_only", False)
        )


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
            existing_yaml=data.existing_yaml,
            errors=data.errors,
            context=data.context,
            history=data.history or [],
            read_only=data.read_only,
            stream=data.stream
        )

        # 5. Return structured response
        return {
            "response": result.response,
            "response_yaml": result.response_yaml,
            "suggested_code": result.suggested_code,
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
