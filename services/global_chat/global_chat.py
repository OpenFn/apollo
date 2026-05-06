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

from langfuse import observe, propagate_attributes, get_client as get_langfuse_client
from util import ApolloError, create_logger
from langfuse_util import should_track, build_tags
from global_chat.config_loader import ConfigLoader
from global_chat.router import RouterAgent

logger = create_logger(__name__)


@dataclass
class Payload:
    """Input payload for global agent."""
    content: str
    workflow_yaml: Optional[str] = None
    page: Optional[str] = None
    meta: Optional[Dict] = None
    history: Optional[List[Dict]] = None
    options: Optional[Dict] = None
    api_key: Optional[str] = None
    attachments: Optional[List[Dict]] = None
    user: Optional[Dict] = None
    metrics_opt_in: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        """Validate and create Payload from dict."""
        if "content" not in data:
            raise ApolloError(400, "content is required")

        return cls(
            content=data["content"],
            workflow_yaml=data.get("workflow_yaml"),
            page=data.get("page"),
            meta=data.get("meta"),
            history=data.get("history"),
            options=data.get("options"),
            api_key=data.get("api_key"),
            attachments=data.get("attachments"),
            user=data.get("user"),
            metrics_opt_in=data.get("metrics_opt_in"),
        )

    def get_stream(self) -> bool:
        """Extract stream flag from options."""
        return (self.options or {}).get("stream", False)


@observe(name="global_chat", capture_input=False)
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict:
    """
    Main entry point for global agent service.

    Args:
        data_dict: Input payload as dictionary
        test_hooks: Optional test-only dict; see testing/anthropic_mock.py.

    Returns:
        Response dictionary with response, attachments, history, usage, meta
    """
    try:
        # 1. Validate payload
        data = Payload.from_dict(data_dict)
        logger.info(f"Global agent called with content: {data.content[:100]}...")

        session_id = data.meta.get("session_id") if data.meta else None
        user_info = data.user or {}
        tracking = should_track(data_dict)

        if tracking:
            langfuse = get_langfuse_client()
            langfuse.update_current_span(input=data.content)

        with propagate_attributes(
            session_id=session_id,
            user_id=user_info.get("id") if tracking else None,
            tags=build_tags("global_chat", user_info) if tracking else None,
            metadata=None if tracking else {"tracing_disabled": "true"},
        ):
            # 2. Load configuration
            config_loader = ConfigLoader("config.yaml")

            # 3. Initialize router
            router = RouterAgent(config_loader, data.api_key, test_hooks=test_hooks)

            # 4. Route and execute
            result = router.route_and_execute(
                content=data.content,
                workflow_yaml=data.workflow_yaml,
                page=data.page,
                history=data.history or [],
                stream=data.get_stream(),
                attachments=data.attachments or [],
                user=data.user,
                metrics_opt_in=data.metrics_opt_in,
            )

            # 5. Return structured response
            return {
                "response": result.response,
                "attachments": result.attachments,
                "history": result.history,
                "usage": result.usage,
                "meta": result.meta
            }

    except ApolloError as e:
        logger.error(f"ApolloError in global_chat: {e}")
        raise e
    except Exception as e:
        logger.exception("Unexpected error in global_chat")
        raise ApolloError(500, str(e))
