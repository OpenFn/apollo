"""
Router Agent - Lightweight routing for global agent requests.

Routes requests to workflow_chat, job_chat, or planner based on user intent.
"""

import json
import os

# Import utilities from parent services directory
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from anthropic import Anthropic

sys.path.append(str(Path(__file__).parent.parent))

from global_chat.config_loader import ConfigLoader
from langfuse import get_client as get_langfuse_client
from langfuse import observe
from models import resolve_model
from streaming_util import StreamManager
from util import ApolloError, create_logger, sum_usage
from yaml_utils import find_job_in_yaml, get_page_view, get_step_name_from_page, stitch_job_code, workflow_has_job_code

logger = create_logger(__name__)


@dataclass
class RouterDecision:
    """Decision from router about where to send the request."""

    destination: str  # "workflow_agent" | "job_code_agent" | "planner"
    confidence: int  # 1-5, where 5 is highest confidence
    job_key: Optional[str] = None  # Target job key when routing to job_code_agent


@dataclass
class RouterResult:
    """Result from router or passthrough."""

    response: str
    response_segments: List[Dict]
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

    @observe(name="router")
    def route_and_execute(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        attachments: Optional[List[Dict]] = None,
        user: Optional[Dict] = None,
        metrics_opt_in: Optional[bool] = None,
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
            "cache_read_input_tokens": 0,
        }

        self._input_attachments = attachments or []
        self._user = user
        self._metrics_opt_in = metrics_opt_in
        # One stream manager shared by whichever agents serve this request, so
        # a handed-over request continues the same stream instead of starting
        # a second message lifecycle.
        self._stream_manager = StreamManager(model=self.model, stream=stream)

        try:
            decision = self._make_routing_decision(content, workflow_yaml, page, history)
            logger.info(
                f"Router decision: {decision.destination} (confidence: {decision.confidence}, job_key: {decision.job_key})",
            )
        except Exception as e:
            logger.warning(
                f"Routing decision failed ({type(e).__name__}). Defaulting to planner for safety.",
            )
            decision = RouterDecision(destination="planner", confidence=1)

        # Direct routes are a fast path for clear-cut requests; when the router
        # itself is unsure, take the path that can't be wrong. Costs nothing:
        # the confidence comes back in the same routing call.
        if decision.destination in ("workflow_agent", "job_code_agent") and decision.confidence < 3:
            logger.warning(
                f"Low router confidence ({decision.confidence}) for {decision.destination} — routing to planner instead",
            )
            self._track_reroute({"low_confidence_reroute": decision.destination})
            decision = RouterDecision(destination="planner", confidence=decision.confidence)

        if decision.destination == "workflow_agent":
            result = self._route_to_workflow_chat(content, workflow_yaml, page, history, stream, decision.confidence)
        elif decision.destination == "job_code_agent":
            result = self._route_to_job_chat(
                content, workflow_yaml, page, history, stream, decision.confidence, decision.job_key,
            )
        else:
            result = self._route_to_planner(content, workflow_yaml, page, history, stream, decision.confidence)

        return result

    @observe(name="routing_decision")
    def _make_routing_decision(
        self, content: str, workflow_yaml: Optional[str], page: Optional[str], history: List[Dict],
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
                        {"type": "null"},
                    ],
                },
            },
            "required": ["destination", "confidence", "job_key"],
            "additionalProperties": False,
        }

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=[{"type": "text", "text": system_prompt}],
            messages=[
                {"role": "user", "content": routing_message},
            ],
            output_config={"format": {"type": "json_schema", "schema": routing_schema}},
        )

        self.routing_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        }

        response_text = response.content[0].text if response.content else "{}"

        try:
            decision_data = json.loads(response_text)
            return RouterDecision(
                destination=decision_data["destination"],
                confidence=decision_data.get("confidence", 3),
                job_key=decision_data.get("job_key"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            # Neither the exception nor the response body: `response_text` is
            # the model's reply to a prompt built from the user's workflow.
            logger.error(
                f"Failed to parse routing decision ({type(e).__name__}); "
                f"{len(response_text)} characters received",
            )
            raise

    def _build_routing_message(
        self, content: str, workflow_yaml: Optional[str], page: Optional[str], history: List[Dict],
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
                msg = turn.get("content", "")[:1000]
                parts.append(f"  {role}: {msg}")

        if workflow_yaml:
            parts.append(f"\n[Workflow YAML attached, length: {len(workflow_yaml)} chars]")
            if workflow_has_job_code(workflow_yaml):
                parts.append("[Steps contain job code]")
            else:
                parts.append("[All step bodies are empty/placeholder]")
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
        self, content: str, workflow_yaml: Optional[str], page: Optional[str], history: List[Dict], stream: bool, confidence: int,
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
            "api_key": self.api_key,
            "meta": {"user": self._user} if self._user else None,
            "metrics_opt_in": self._metrics_opt_in,
            "subagent": True,
            "_stream_manager": self._stream_manager,
        }

        result = workflow_chat_main(payload)

        if result.get("handover"):
            return self._handover_to_planner(
                "workflow_agent", result, content, workflow_yaml, page, history, stream, confidence,
            )

        total_usage = sum_usage(self.routing_usage, result["usage"])

        attachments = []
        response_yaml = result.get("response_yaml")
        if response_yaml:
            attachments.append({"type": "workflow_yaml", "content": response_yaml})

        return RouterResult(
            response=result["response"],
            response_segments=[{"type": "text", "content": result["response"]}],
            attachments=attachments,
            history=result["history"].copy(),
            usage=total_usage,
            meta={"agents": ["router", "workflow_agent"], "router_confidence": confidence},
        )

    def _route_to_job_chat(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int,
        router_job_key: Optional[str] = None,
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

        # Router's job_key wins if it resolves to a job in the YAML;
        # otherwise fall back to the step parsed from the page URL
        job_context = {}
        matched_job_key, job_data = None, None

        if workflow_yaml:
            if router_job_key:
                matched_job_key, job_data = find_job_in_yaml(workflow_yaml, router_job_key)
            if matched_job_key is None:
                page_step = get_step_name_from_page(page)
                if page_step:
                    matched_job_key, job_data = find_job_in_yaml(workflow_yaml, page_step)

        if matched_job_key is None:
            # Distinguish the failure modes so the cause is visible in logs:
            # no YAML sent vs. a YAML shape we can't read (e.g. Lightning's
            # project format nests jobs under `workflows:` rather than a
            # top-level `jobs:`) vs. YAML present but the job name not found.
            if not workflow_yaml:
                reason = "no workflow_yaml was provided in the request"
            else:
                try:
                    parsed = yaml.safe_load(workflow_yaml)
                    if not isinstance(parsed, dict):
                        reason = "workflow_yaml did not parse to a mapping"
                    elif "jobs" not in parsed:
                        reason = f"workflow_yaml has no top-level 'jobs' key (top-level keys: {list(parsed.keys())})"
                    else:
                        reason = f"job not found among keys {list(parsed['jobs'].keys())}"
                except Exception as error:
                    # Type only: a PyYAML mark quotes the document.
                    reason = f"workflow_yaml failed to parse ({type(error).__name__})"
            logger.warning(
                f"No job matched for router_job_key='{router_job_key}' or page='{page}': {reason}",
            )

        if job_data:
            if job_data.get("body"):
                job_context["expression"] = job_data["body"]
            if job_data.get("adaptor"):
                job_context["adaptor"] = job_data["adaptor"]
            if job_data.get("name"):
                job_context["page_name"] = job_data["name"]
        if matched_job_key:
            # Tells job_chat's subagent prompt which step is focused/editable
            job_context["job_key"] = matched_job_key

        # What the user actually has on screen, independent of which step we
        # focus for editing: a specific step's code, or the workflow canvas.
        # Only the router knows this (planner/prod calls omit it, so the prompt
        # grounding line stays off). Fail safe: only claim a step the page name
        # resolves to a real job — a mis-split name simply yields no line.
        page_view, page_step = get_page_view(page)
        if page_view == "step" and workflow_yaml:
            _, viewed_job = find_job_in_yaml(workflow_yaml, page_step)
            if viewed_job and viewed_job.get("name"):
                job_context["viewing"] = viewed_job["name"]
        elif page_view == "overview":
            job_context["viewing"] = "canvas"

        clean_history = [{"role": t["role"], "content": t["content"]} for t in history]
        enriched_content = self._format_attachments_for_content(content)

        payload = {
            "content": enriched_content,
            "context": job_context,
            "suggest_code": True,
            "history": clean_history,
            "stream": stream,
            "api_key": self.api_key,
            "meta": {"user": self._user} if self._user else None,
            "metrics_opt_in": self._metrics_opt_in,
            "subagent": True,
            "workflow_yaml": workflow_yaml,
            "_stream_manager": self._stream_manager,
        }

        result = job_chat_main(payload)

        if result.get("handover"):
            return self._handover_to_planner(
                "job_code_agent", result, content, workflow_yaml, page, history, stream, confidence,
            )

        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Stitch suggested_code back into the workflow YAML. The full YAML is
        # the only artifact returned — no separate job_code attachment.
        attachments = []
        if result.get("suggested_code"):
            if workflow_yaml and matched_job_key:
                updated_yaml = stitch_job_code(workflow_yaml, matched_job_key, result["suggested_code"])
                attachments.append({"type": "workflow_yaml", "content": updated_yaml})
            else:
                logger.warning(
                    f"suggested_code generated but no job matched for page '{page}' - code dropped from response",
                )

        return RouterResult(
            response=result["response"],
            response_segments=[{"type": "text", "content": result["response"]}],
            attachments=attachments,
            history=result["history"].copy(),
            usage=total_usage,
            meta={"agents": ["router", "job_code_agent"], "router_confidence": confidence},
        )

    def _handover_to_planner(
        self,
        from_agent: str,
        subagent_result: Dict,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int,
    ) -> RouterResult:
        """Reroute a handed-over request to the planner.

        A direct-routed subagent signalled it cannot complete the request
        (wrong route or missing capability). The planner never hands over, so
        this retries at most once. The shared stream manager means the user
        never sees the aborted attempt.
        """
        reason = subagent_result["handover"]
        # Length only: the subagent wrote this about the user's request, so it
        # can quote the workflow or the job body back.
        logger.warning(
            f"{from_agent} handed over ({len(str(reason))} characters). Rerouting to planner",
        )
        self._track_reroute({"handover_from": from_agent, "handover_reason": reason})

        planner_result = self._route_to_planner(content, workflow_yaml, page, history, stream, confidence)
        planner_result.usage = sum_usage(planner_result.usage, subagent_result.get("usage", {}))
        return planner_result

    def _track_reroute(self, metadata: Dict) -> None:
        """Record reroute diagnostics on the Langfuse trace (opt-in per request).

        Deliberately kept out of the response meta: the frontend does nothing
        with these, they are for Langfuse analysis only. Server logs carry the
        same information when tracking is off.
        """
        if not self._metrics_opt_in:
            return
        try:
            get_langfuse_client().update_current_span(metadata=metadata)
        except Exception:
            logger.warning("Failed to record reroute metadata in Langfuse")

    def _route_to_planner(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        confidence: int,
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
            stream=stream,
            user=self._user,
            metrics_opt_in=self._metrics_opt_in,
            stream_manager=self._stream_manager,
        )

        total_usage = sum_usage(self.routing_usage, planner_result.usage)

        meta = planner_result.meta.copy()
        meta["router_confidence"] = confidence

        return RouterResult(
            response=planner_result.response,
            response_segments=planner_result.response_segments,
            attachments=planner_result.attachments,
            history=planner_result.history,
            usage=total_usage,
            meta=meta,
        )
