"""
Router Agent - Lightweight routing for global agent requests.

Routes requests to workflow_chat, job_chat, or planner based on user intent.
"""
import os
import json
from typing import List, Dict, Optional
from dataclasses import dataclass
from anthropic import Anthropic

# Import utilities from parent services directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from util import create_logger, ApolloError, sum_usage
from global_chat.config_loader import ConfigLoader
from models import resolve_model
from global_chat.yaml_utils import get_step_name_from_page, find_job_in_yaml, stitch_job_code

logger = create_logger(__name__)


@dataclass
class RouterDecision:
    """Decision from router about where to send the request."""
    destination: str  # "workflow_agent" | "job_code_agent" | "planner"
    confidence: int   # 1-5, where 5 is highest confidence
    job_key: Optional[str] = None  # Target job key when routing to job_code_agent


@dataclass
class RouterResult:
    """Result from router or passthrough."""
    response: str
    attachments: List[Dict]
    history: List[Dict]
    usage: Dict
    meta: Dict


class RouterAgent:
    """
    Lightweight routing agent using Claude Haiku.

    Routes requests to:
    - workflow_chat (for workflow YAML structure)
    - job_chat (for job code on a specific step)
    - planner (for complex multi-step tasks)
    """

    def __init__(self, config_loader: ConfigLoader, api_key: Optional[str] = None):
        self.config_loader = config_loader
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        self.client = Anthropic(api_key=self.api_key)

        router_config = config_loader.config.get("router", {})
        self.model = resolve_model(router_config.get("model", "claude-haiku"))
        self.max_tokens = router_config.get("max_tokens", 500)
        self.temperature = router_config.get("temperature", 0.0)

        logger.info(f"RouterAgent initialized with model: {self.model}")

    def route_and_execute(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        attachments: Optional[List[Dict]] = None
    ) -> RouterResult:
        """
        Route request to appropriate handler and execute.

        Args:
            content: User message
            workflow_yaml: Full workflow YAML string (including job bodies)
            page: Current page URL (e.g. workflows/name/step-name)
            history: Conversation history
            stream: Streaming flag
            attachments: Optional input attachments (e.g. logs, dataclips)

        Returns:
            RouterResult with response, attachments, history, usage, meta
        """
        logger.info("Router.route_and_execute() called")

        self.routing_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }

        self._input_attachments = attachments or []

        try:
            decision = self._make_routing_decision(content, workflow_yaml, page, history)
            logger.info(f"Router decision: {decision.destination} (confidence: {decision.confidence}, job_key: {decision.job_key})")
        except Exception as e:
            logger.warning(f"Routing decision failed: {e}. Defaulting to planner for safety.")
            decision = RouterDecision(destination="planner", confidence=1)

        if decision.destination == "workflow_agent":
            result = self._route_to_workflow_chat(content, workflow_yaml, history, stream, decision.confidence)
        elif decision.destination == "job_code_agent":
            result = self._route_to_job_chat(content, workflow_yaml, page, history, stream, decision.confidence, decision.job_key)
        else:
            result = self._route_to_planner(content, workflow_yaml, page, history, stream, decision.confidence)

        return result

    def _make_routing_decision(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict]
    ) -> RouterDecision:
        """Make routing decision using Claude Haiku."""
        routing_message = self._build_routing_message(content, workflow_yaml, page, history)
        system_prompt = self.config_loader.get_prompt("router_system_prompt")

        routing_schema = {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "confidence": {"type": "integer"},
                "job_key": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"}
                    ]
                }
            },
            "required": ["destination", "confidence", "job_key"],
            "additionalProperties": False
        }

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=[{"type": "text", "text": system_prompt}],
            messages=[
                {"role": "user", "content": routing_message}
            ],
            output_config={"format": {"type": "json_schema", "schema": routing_schema}}
        )

        self.routing_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0)
        }

        response_text = response.content[0].text if response.content else "{}"

        try:
            decision_data = json.loads(response_text)
            return RouterDecision(
                destination=decision_data["destination"],
                confidence=decision_data.get("confidence", 3),
                job_key=decision_data.get("job_key")
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse routing decision: {e}. Response: {response_text}")
            raise

    def _build_routing_message(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict]
    ) -> str:
        """Build message for routing decision."""
        parts = []

        parts.append(f"User request: {content}")

        if page:
            parts.append(f"\nCurrent page: {page}")

        if history and len(history) >= 2:
            recent_history = history[-2:]
            parts.append("\nRecent conversation:")
            for turn in recent_history:
                role = turn.get("role", "unknown")
                msg = turn.get("content", "")[:200]
                parts.append(f"  {role}: {msg}")

        if workflow_yaml:
            parts.append(f"\n[Workflow YAML attached, length: {len(workflow_yaml)} chars]")
            parts.append(f"YAML content:\n{workflow_yaml}")

        return "\n".join(parts)

    def _format_attachments_for_content(self, content: str) -> str:
        """Append input attachments to content string for subagent context."""
        if not self._input_attachments:
            return content

        parts = [content]
        for attachment in self._input_attachments:
            att_type = attachment.get("type", "unknown")
            att_content = attachment.get("content", "")
            parts.append(f"\n\n[Attached {att_type}]\n{att_content}")
        return "\n".join(parts)

    def _route_to_workflow_chat(
        self,
        content: str,
        workflow_yaml: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Route directly to workflow_chat."""
        from workflow_chat.workflow_chat import main as workflow_chat_main

        logger.info("Routing to workflow_chat")

        clean_history = [{"role": t["role"], "content": t["content"]} for t in history]
        enriched_content = self._format_attachments_for_content(content)

        payload = {
            "content": enriched_content,
            "existing_yaml": workflow_yaml,
            "history": clean_history,
            "stream": stream,
            "api_key": self.api_key
        }

        result = workflow_chat_main(payload)
        total_usage = sum_usage(self.routing_usage, result["usage"])

        attachments = []
        response_yaml = result.get("response_yaml")
        if response_yaml:
            attachments.append({"type": "workflow_yaml", "content": response_yaml})

        return RouterResult(
            response=result["response"],
            attachments=attachments,
            history=result["history"].copy(),
            usage=total_usage,
            meta={
                "agents": ["router", "workflow_agent"],
                "router_confidence": confidence
            }
        )

    def _route_to_job_chat(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int,
        router_job_key: Optional[str] = None
    ) -> RouterResult:
        """
        Route directly to job_chat.

        Extracts the focused job's code and adaptor from the workflow YAML using
        the step name parsed from the page URL (or the router's job_key as
        fallback), then stitches the suggested code back into the workflow YAML
        before returning.
        """
        from job_chat.job_chat import main as job_chat_main

        logger.info("Routing to job_chat")

        # Build job context from YAML using step name from page,
        # falling back to the router's job_key decision
        job_context = {}
        matched_job_key = None

        step_name = get_step_name_from_page(page) or router_job_key
        if workflow_yaml and step_name:
            matched_job_key, job_data = find_job_in_yaml(workflow_yaml, step_name)
            if matched_job_key is None:
                logger.warning(f"No job found in YAML matching step name '{step_name}'")
            if job_data:
                if job_data.get("body"):
                    job_context["expression"] = job_data["body"]
                if job_data.get("adaptor"):
                    job_context["adaptor"] = job_data["adaptor"]
                if job_data.get("name"):
                    job_context["page_name"] = job_data["name"]

        clean_history = [{"role": t["role"], "content": t["content"]} for t in history]
        enriched_content = self._format_attachments_for_content(content)

        payload = {
            "content": enriched_content,
            "context": job_context,
            "suggest_code": True,
            "history": clean_history,
            "stream": stream,
            "api_key": self.api_key
        }

        result = job_chat_main(payload)
        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Stitch suggested_code back into workflow YAML
        updated_yaml = workflow_yaml
        if result.get("suggested_code") and workflow_yaml and matched_job_key:
            updated_yaml = stitch_job_code(workflow_yaml, matched_job_key, result["suggested_code"])
        elif result.get("suggested_code") and not matched_job_key:
            logger.warning(f"suggested_code generated but no job matched for page '{page}' - YAML not updated")

        attachments = []
        if result.get("suggested_code"):
            job_code_attachment = {"type": "job_code", "content": result["suggested_code"]}
            if matched_job_key:
                job_code_attachment["job_key"] = matched_job_key
            attachments.append(job_code_attachment)
        if updated_yaml:
            attachments.append({"type": "workflow_yaml", "content": updated_yaml})

        return RouterResult(
            response=result["response"],
            attachments=attachments,
            history=result["history"].copy(),
            usage=total_usage,
            meta={
                "agents": ["router", "job_code_agent"],
                "router_confidence": confidence
            }
        )

    def _route_to_planner(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Delegate to PlannerAgent for complex orchestration."""
        from global_chat.planner import PlannerAgent

        logger.info("Routing to planner")

        clean_history = [{"role": t["role"], "content": t["content"]} for t in history]
        enriched_content = self._format_attachments_for_content(content)

        planner = PlannerAgent(self.config_loader, self.api_key)
        planner_result = planner.run(
            content=enriched_content,
            workflow_yaml=workflow_yaml,
            page=page,
            history=clean_history,
            stream=stream
        )

        total_usage = sum_usage(self.routing_usage, planner_result.usage)

        meta = planner_result.meta.copy()
        meta["router_confidence"] = confidence

        return RouterResult(
            response=planner_result.response,
            attachments=planner_result.attachments,
            history=planner_result.history,
            usage=total_usage,
            meta=meta
        )

