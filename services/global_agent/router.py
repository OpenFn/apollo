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
from global_agent.config_loader import ConfigLoader

logger = create_logger(__name__)


@dataclass
class RouterDecision:
    """Decision from router about where to send the request."""
    destination: str  # "workflow_agent" | "job_code_agent" | "planner"
    confidence: int   # 1-5, where 5 is highest confidence


@dataclass
class Attachment:
    """Output attachment."""
    type: str
    content: str


@dataclass
class RouterResult:
    """Result from router or passthrough."""
    response: str
    attachments: List[Attachment]
    history: List[Dict]
    usage: Dict
    meta: Dict


class RouterAgent:
    """
    Lightweight routing agent using Claude Haiku.

    Routes requests to:
    - workflow_chat (for workflow YAML)
    - job_chat (for job code)
    - planner (for complex multi-step tasks)
    """

    def __init__(self, config_loader: ConfigLoader, api_key: Optional[str] = None):
        """
        Initialize router agent.

        Args:
            config_loader: Configuration loader instance
            api_key: Optional API key override
        """
        self.config_loader = config_loader
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        self.client = Anthropic(api_key=self.api_key)

        # Get router config
        router_config = config_loader.config.get("router", {})
        self.model = router_config.get("model", "claude-haiku-4-5-20251001")
        self.max_tokens = router_config.get("max_tokens", 500)
        self.temperature = router_config.get("temperature", 0.0)

        logger.info(f"RouterAgent initialized with model: {self.model}")

    def route_and_execute(
        self,
        content: str,
        workflow_yaml: Optional[str],
        errors: Optional[str],
        job_code_context: Optional[Dict],
        history: List[Dict],
        read_only: bool,
        stream: bool
    ) -> RouterResult:
        """
        Route request to appropriate handler and execute.

        Args:
            content: User message
            workflow_yaml: YAML workflow
            errors: Error context
            job_code_context: Job code context (with expression, page_name, adaptor)
            history: Conversation history
            read_only: Read-only mode flag
            stream: Streaming flag

        Returns:
            RouterResult with response, attachments, history, usage, meta
        """
        logger.info("Router.route_and_execute() called")

        # Make routing decision
        try:
            decision = self._make_routing_decision(content, workflow_yaml, errors, job_code_context, history)
            logger.info(f"Router decision: {decision.destination} (confidence: {decision.confidence})")
        except Exception as e:
            logger.warning(f"Routing decision failed: {e}. Defaulting to planner for safety.")
            decision = RouterDecision(destination="planner", confidence=1)

        # Execute based on decision
        if decision.destination == "workflow_agent":
            result = self._route_to_workflow_chat(
                content, workflow_yaml, errors, history, read_only, stream, decision.confidence
            )
        elif decision.destination == "job_code_agent":
            result = self._route_to_job_chat(
                content, job_code_context, history, stream, decision.confidence
            )
        else:  # planner
            result = self._route_to_planner(
                content, workflow_yaml, errors, job_code_context, history, read_only, stream, decision.confidence
            )

        return result

    def _make_routing_decision(
        self,
        content: str,
        workflow_yaml: Optional[str],
        errors: Optional[str],
        job_code_context: Optional[Dict],
        history: List[Dict]
    ) -> RouterDecision:
        """
        Make routing decision using Claude Haiku.

        Args:
            content: User message
            workflow_yaml: YAML workflow
            errors: Error context
            job_code_context: Job code context
            history: Conversation history

        Returns:
            RouterDecision with destination and confidence
        """
        # Build routing message with context
        routing_message = self._build_routing_message(content, workflow_yaml, errors, job_code_context, history)

        # Get system prompt
        system_prompt = self.config_loader.get_prompt("router_system_prompt")

        # Call Haiku with prefilled response
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=[{"type": "text", "text": system_prompt}],
            messages=[
                {"role": "user", "content": routing_message},
                {"role": "assistant", "content": '{"destination": "'}  # Prefill to constrain format
            ]
        )

        # Store routing usage for aggregation
        self.routing_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0)
        }

        # Parse response - prepend the prefilled part back
        response_text = response.content[0].text if response.content else ""
        full_response = '{"destination": "' + response_text

        try:
            # Find the closing brace to extract just the JSON object
            # Handle case where LLM adds explanation after JSON
            brace_count = 1
            json_end = 0
            for i, char in enumerate(full_response[1:], 1):  # Start after opening brace
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break

            if json_end > 0:
                json_only = full_response[:json_end]
            else:
                json_only = full_response

            decision_data = json.loads(json_only)
            return RouterDecision(
                destination=decision_data["destination"],
                confidence=decision_data.get("confidence", 3)
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse routing decision: {e}. Response: {full_response}")
            raise

    def _build_routing_message(
        self,
        content: str,
        workflow_yaml: Optional[str],
        errors: Optional[str],
        job_code_context: Optional[Dict],
        history: List[Dict]
    ) -> str:
        """
        Build message for routing decision with relevant context.

        Args:
            content: User message
            workflow_yaml: YAML workflow
            errors: Error context
            job_code_context: Job code context
            history: Conversation history

        Returns:
            Formatted routing message string
        """
        parts = []

        # Current user request
        parts.append(f"User request: {content}")

        # Last 2 turns for context
        if history and len(history) >= 2:
            recent_history = history[-2:]
            parts.append("\nRecent conversation:")
            for turn in recent_history:
                role = turn.get("role", "unknown")
                msg = turn.get("content", "")[:200]
                parts.append(f"  {role}: {msg}")

        # Attachments (full content for accurate routing)
        if workflow_yaml:
            parts.append(f"\n[YAML attached, length: {len(workflow_yaml)} chars]")
            parts.append(f"YAML content:\n{workflow_yaml}")

        if job_code_context and job_code_context.get("expression"):
            job_code = job_code_context["expression"]
            parts.append(f"\n[Job code attached, length: {len(job_code)} chars]")
            parts.append(f"Job code:\n{job_code}")

        if errors:
            parts.append(f"\nErrors: {errors}")

        # Page context
        if job_code_context:
            if job_code_context.get("page_name"):
                parts.append(f"\nCurrent page: {job_code_context['page_name']}")
            if job_code_context.get("adaptor"):
                parts.append(f"Adaptor: {job_code_context['adaptor']}")

        return "\n".join(parts)

    def _route_to_workflow_chat(
        self,
        content: str,
        workflow_yaml: Optional[str],
        errors: Optional[str],
        history: List[Dict],
        read_only: bool,
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Route directly to workflow_chat."""
        from workflow_chat.workflow_chat import main as workflow_chat_main

        logger.info("Routing to workflow_chat")

        # Strip attachments from history for API compatibility
        clean_history = []
        for turn in history:
            clean_turn = {"role": turn["role"], "content": turn["content"]}
            clean_history.append(clean_turn)

        payload = {
            "content": content,
            "existing_yaml": workflow_yaml,
            "errors": errors,
            "history": clean_history,
            "read_only": read_only,
            "stream": stream
        }

        result = workflow_chat_main(payload)
        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Transform response_yaml to attachments
        attachments = []
        if result.get("response_yaml"):
            attachments.append(Attachment(type="workflow_yaml", content=result["response_yaml"]))

        # Add attachments to last history entry
        updated_history = result["history"].copy()
        if updated_history and updated_history[-1].get("role") == "assistant":
            updated_history[-1]["attachments"] = [{"type": a.type, "content": a.content} for a in attachments]

        return RouterResult(
            response=result["response"],
            attachments=attachments,
            history=updated_history,
            usage=total_usage,
            meta={
                "agents": ["router", "workflow_agent"],
                "router_confidence": confidence
            }
        )

    def _route_to_job_chat(
        self,
        content: str,
        job_code_context: Optional[Dict],
        history: List[Dict],
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Route directly to job_chat."""
        from job_chat.job_chat import main as job_chat_main

        logger.info("Routing to job_chat")

        # Strip attachments from history for API compatibility
        clean_history = []
        for turn in history:
            clean_turn = {"role": turn["role"], "content": turn["content"]}
            clean_history.append(clean_turn)

        payload = {
            "content": content,
            "context": job_code_context or {},
            "suggest_code": True,
            "history": clean_history,
            "stream": stream
        }

        result = job_chat_main(payload)
        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Transform suggested_code to attachments
        attachments = []
        if result.get("suggested_code"):
            attachments.append(Attachment(type="job_code", content=result["suggested_code"]))

        # Add attachments to last history entry
        updated_history = result["history"].copy()
        if updated_history and updated_history[-1].get("role") == "assistant":
            updated_history[-1]["attachments"] = [{"type": a.type, "content": a.content} for a in attachments]

        return RouterResult(
            response=result["response"],
            attachments=attachments,
            history=updated_history,
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
        errors: Optional[str],
        job_code_context: Optional[Dict],
        history: List[Dict],
        read_only: bool,
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Delegate to PlannerAgent for complex orchestration."""
        from global_agent.planner import PlannerAgent

        logger.info("Routing to planner")

        # Strip attachments from history for API compatibility
        clean_history = []
        for turn in history:
            clean_turn = {"role": turn["role"], "content": turn["content"]}
            clean_history.append(clean_turn)

        planner = PlannerAgent(self.config_loader, self.api_key)
        planner_result = planner.run(
            content=content,
            existing_yaml=workflow_yaml,
            errors=errors,
            context=job_code_context,
            history=clean_history,
            read_only=read_only,
            stream=stream
        )

        total_usage = sum_usage(self.routing_usage, planner_result.usage)

        # Merge router confidence into planner meta
        meta = planner_result.meta.copy()
        meta["router_confidence"] = confidence

        # Add attachments to last history entry if it's an assistant message
        updated_history = planner_result.history.copy() if planner_result.history else []
        if updated_history and updated_history[-1].get("role") == "assistant":
            updated_history[-1]["attachments"] = [{"type": a.type, "content": a.content} for a in planner_result.attachments]

        return RouterResult(
            response=planner_result.response,
            attachments=planner_result.attachments,
            history=updated_history,
            usage=total_usage,
            meta=meta
        )
