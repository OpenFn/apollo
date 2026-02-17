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
class RouterResult:
    """Result from router or passthrough."""
    response: str
    response_yaml: Optional[str]
    suggested_code: Optional[str]
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
        existing_yaml: Optional[str],
        errors: Optional[str],
        context: Optional[Dict],
        history: List[Dict],
        read_only: bool,
        stream: bool
    ) -> RouterResult:
        """
        Route request to appropriate handler and execute.

        Args:
            content: User message
            existing_yaml: YAML workflow (as string)
            errors: Error context
            context: Job code context (with expression, page_name, adaptor)
            history: Conversation history
            read_only: Read-only mode flag
            stream: Streaming flag

        Returns:
            RouterResult with response, YAML, code, history, usage, meta
        """
        logger.info("Router.route_and_execute() called")

        # Make routing decision
        try:
            decision = self._make_routing_decision(content, existing_yaml, errors, context, history)
            logger.info(f"Router decision: {decision.destination} (confidence: {decision.confidence})")
        except Exception as e:
            logger.warning(f"Routing decision failed: {e}. Defaulting to planner for safety.")
            decision = RouterDecision(destination="planner", confidence=1)

        # Execute based on decision
        if decision.destination == "workflow_agent":
            result = self._route_to_workflow_chat(
                content, existing_yaml, errors, history, read_only, stream, decision.confidence
            )
        elif decision.destination == "job_code_agent":
            result = self._route_to_job_chat(
                content, context, history, stream, decision.confidence
            )
        else:  # planner
            result = self._route_to_planner(
                content, existing_yaml, errors, context, history, read_only, stream, decision.confidence
            )

        return result

    def _make_routing_decision(
        self,
        content: str,
        existing_yaml: Optional[str],
        errors: Optional[str],
        context: Optional[Dict],
        history: List[Dict]
    ) -> RouterDecision:
        """
        Make routing decision using Claude Haiku.

        Args:
            content: User message
            existing_yaml: YAML workflow
            errors: Error context
            context: Job code context
            history: Conversation history

        Returns:
            RouterDecision with destination and confidence
        """
        # Build routing message with context
        routing_message = self._build_routing_message(content, existing_yaml, errors, context, history)

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
        existing_yaml: Optional[str],
        errors: Optional[str],
        context: Optional[Dict],
        history: List[Dict]
    ) -> str:
        """
        Build message for routing decision with relevant context.

        Args:
            content: User message
            existing_yaml: YAML workflow
            errors: Error context
            context: Job code context
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
                msg = turn.get("content", "")[:200]  # Truncate long messages
                parts.append(f"  {role}: {msg}")

        # Attachments (full content for accurate routing)
        if existing_yaml:
            parts.append(f"\n[YAML attached, length: {len(existing_yaml)} chars]")
            parts.append(f"YAML content:\n{existing_yaml}")

        if context and context.get("expression"):
            job_code = context["expression"]
            parts.append(f"\n[Job code attached, length: {len(job_code)} chars]")
            parts.append(f"Job code:\n{job_code}")

        if errors:
            parts.append(f"\nErrors: {errors}")

        # Page context
        if context:
            if context.get("page_name"):
                parts.append(f"\nCurrent page: {context['page_name']}")
            if context.get("adaptor"):
                parts.append(f"Adaptor: {context['adaptor']}")

        return "\n".join(parts)

    def _route_to_workflow_chat(
        self,
        content: str,
        existing_yaml: Optional[str],
        errors: Optional[str],
        history: List[Dict],
        read_only: bool,
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Route directly to workflow_chat (called when decision is 'workflow_agent')."""
        from workflow_chat.workflow_chat import main as workflow_chat_main

        logger.info("Routing to workflow_chat")

        payload = {
            "content": content,
            "existing_yaml": existing_yaml,
            "errors": errors,
            "history": history,
            "read_only": read_only,
            "stream": stream
        }

        # Call service directly - let ApolloError propagate if service fails
        result = workflow_chat_main(payload)

        # Aggregate token usage
        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Return as RouterResult with metadata
        return RouterResult(
            response=result["response"],
            response_yaml=result.get("response_yaml"),
            suggested_code=None,
            history=result["history"],
            usage=total_usage,
            meta={
                "router_decision": "workflow_agent",
                "router_confidence": confidence,
                "direct_passthrough": True
            }
        )

    def _route_to_job_chat(
        self,
        content: str,
        context: Optional[Dict],
        history: List[Dict],
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Route directly to job_chat (called when decision is 'job_code_agent')."""
        from job_chat.job_chat import main as job_chat_main

        logger.info("Routing to job_chat")

        payload = {
            "content": content,
            "context": context or {},
            "suggest_code": True,
            "history": history,
            "stream": stream
        }

        # Call service directly - let ApolloError propagate if service fails
        result = job_chat_main(payload)

        # Aggregate token usage
        total_usage = sum_usage(self.routing_usage, result["usage"])

        # Return as RouterResult with metadata
        return RouterResult(
            response=result["response"],
            response_yaml=None,
            suggested_code=result.get("suggested_code"),
            history=result["history"],
            usage=total_usage,
            meta={
                **result.get("meta", {}),
                "router_decision": "job_code_agent",
                "router_confidence": confidence,
                "direct_passthrough": True
            }
        )

    def _route_to_planner(
        self,
        content: str,
        existing_yaml: Optional[str],
        errors: Optional[str],
        context: Optional[Dict],
        history: List[Dict],
        read_only: bool,
        stream: bool,
        confidence: int
    ) -> RouterResult:
        """Delegate to PlannerAgent for complex orchestration."""
        from global_agent.planner import PlannerAgent

        logger.info("Routing to planner")

        planner = PlannerAgent(self.config_loader, self.api_key)
        planner_result = planner.run(
            content=content,
            existing_yaml=existing_yaml,
            errors=errors,
            context=context,
            history=history,
            read_only=read_only,
            stream=stream
        )

        # Aggregate token usage
        total_usage = sum_usage(self.routing_usage, planner_result.usage)

        # Convert to RouterResult
        return RouterResult(
            response=planner_result.response,
            response_yaml=planner_result.response_yaml,
            suggested_code=planner_result.suggested_code,
            history=planner_result.history,
            usage=total_usage,
            meta={
                **planner_result.meta,
                "router_decision": "planner",
                "router_confidence": confidence
            }
        )
