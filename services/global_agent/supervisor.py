"""
Supervisor Agent - Coordinates tools and subagents.

Iteration 1: Simple passthrough (no tool calling yet)
Iteration 2: Will add tool-calling loop
"""
import os
from typing import List, Dict, Optional
from dataclasses import dataclass
from anthropic import Anthropic

# Import utilities from parent services directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from util import create_logger, ApolloError
from global_agent.config_loader import ConfigLoader

logger = create_logger(__name__)


@dataclass
class SupervisorResult:
    """Result from supervisor run."""
    response: str
    response_yaml: Optional[str]
    history: List[Dict]
    usage: Dict
    meta: Dict


class SupervisorAgent:
    """
    Supervisor agent that coordinates subagents and tools.

    Iteration 1: Simple LLM call (no tools)
    Iteration 2: Will add tool-calling capability
    """

    def __init__(self, config_loader: ConfigLoader, api_key: Optional[str] = None):
        """
        Initialize supervisor agent.

        Args:
            config_loader: Configuration loader instance
            api_key: Optional API key override
        """
        self.config = config_loader.config
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        self.client = Anthropic(api_key=self.api_key)
        logger.info("SupervisorAgent initialized")

    def run(
        self,
        content: str,
        existing_yaml: Optional[str],
        errors: Optional[str],
        history: List[Dict],
        read_only: bool,
        stream: bool
    ) -> SupervisorResult:
        """
        Run the supervisor agent.

        Iteration 1: Simple passthrough call to Claude
        Iteration 2: Will add tool-calling loop

        Args:
            content: User message
            existing_yaml: YAML workflow (as string, never parsed)
            errors: Error context
            history: Conversation history
            read_only: Read-only mode flag
            stream: Streaming flag (not implemented)

        Returns:
            SupervisorResult with response, YAML, history, usage, meta
        """
        logger.info("Supervisor.run() called (Iteration 1: simple passthrough)")

        # Build system prompt
        system_prompt = self._build_system_prompt()

        # Build messages
        messages = history.copy() if history else []
        messages.append({"role": "user", "content": content})

        # Simple Claude API call (no tools in Iteration 1)
        try:
            response = self.client.messages.create(
                model=self.config["model"],
                max_tokens=self.config["max_tokens"],
                system=system_prompt,
                messages=messages
            )

            # Extract text response
            text_response = ""
            for block in response.content:
                if block.type == "text":
                    text_response += block.text

            # Build result
            result = SupervisorResult(
                response=text_response,
                response_yaml=None,  # No YAML in iteration 1
                history=messages + [
                    {"role": "assistant", "content": text_response}
                ],
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                meta={
                    "iteration": 1,
                    "note": "Simple passthrough - no tools yet"
                }
            )

            logger.info(f"Supervisor completed. Tokens: {response.usage.input_tokens} in, {response.usage.output_tokens} out")
            return result

        except Exception as e:
            logger.exception("Error calling Claude API")
            raise ApolloError(500, f"Claude API error: {str(e)}")

    def _build_system_prompt(self) -> str:
        """
        Build system prompt for supervisor.

        Iteration 1: Simple intro
        Iteration 2: Will add tool descriptions
        """
        return """You are a supervisor agent for the OpenFn platform.

In this iteration, you can only respond to user questions directly.
Tool-calling and subagent coordination will be added in the next iteration.

For now, be helpful and let the user know that tool capabilities are coming soon."""
