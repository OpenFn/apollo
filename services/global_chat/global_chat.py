"""
Global Agent - Main entry point.

This is the supervisor agent that coordinates subagents and tools.
"""
# Import utilities from parent services directory
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.append(str(Path(__file__).parent.parent))

from global_chat.config_loader import ConfigLoader
from global_chat.router import RouterAgent
from langfuse import get_client as get_langfuse_client
from langfuse import observe, propagate_attributes
from langfuse_util import build_generation_diff, build_tags, should_track
from util import APOLLO_VERSION, ApolloError, create_logger

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
            metrics_opt_in=data.get("metrics_opt_in"),
        )

    def get_stream(self) -> bool:
        """Extract stream flag from options."""
        return (self.options or {}).get("stream", False)


@observe(name="global_chat", capture_input=False)
def main(data_dict: dict) -> dict:
    """
    Main entry point for global agent service.

    Args:
        data_dict: Input payload as dictionary

    Returns:
        Response dictionary with response, attachments, history, usage, meta
    """
    try:
        # 1. Validate payload
        data = Payload.from_dict(data_dict)
        logger.info(f"Global agent called with content: {data.content[:100]}...")

        session_id = data.meta.get("session_id") if data.meta else None
        user_info = (data.meta.get("user") or {}) if data.meta else {}
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
            router = RouterAgent(config_loader, data.api_key)

            # 4. Route and execute
            result = router.route_and_execute(
                content=data.content,
                workflow_yaml=data.workflow_yaml,
                page=data.page,
                history=data.history or [],
                stream=data.get_stream(),
                attachments=data.attachments or [],
                user=user_info,
                metrics_opt_in=data.metrics_opt_in,
            )

            if tracking:
                final_yaml = next(
                    (a.get("content") for a in reversed(result.attachments or [])
                     if a.get("type") == "workflow_yaml"),
                    None,
                )
                diff_meta = build_generation_diff(
                    original=data.workflow_yaml,
                    generated=final_yaml,
                    yaml_mode=True,
                )
                if diff_meta:
                    langfuse.update_current_span(metadata=diff_meta)

            # 5. Return structured response
            return {
                "response": result.response,
                "response_segments": result.response_segments,
                "attachments": result.attachments,
                "history": result.history,
                "usage": result.usage,
                "meta": {
                **result.meta,
                "apollo_version": APOLLO_VERSION,
                },
            }

    except ApolloError as e:
        # Type and status only. An ApolloError raised further in wraps an
        # arbitrary inner exception, and `subagent_caller` builds its message
        # from `str(e)` — which can quote client-supplied `workflow_yaml` back.
        logger.error(f"ApolloError in global_chat (code={e.code})")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in global_chat ({type(e).__name__})")
        # Returned to the caller as the error payload, so same treatment.
        raise ApolloError(500, f"Unexpected error in global_chat ({type(e).__name__})")
