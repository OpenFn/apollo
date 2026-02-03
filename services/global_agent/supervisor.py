"""
Supervisor Agent - Coordinates tools and subagents.

Iteration 2: Full tool-calling implementation
"""
import os
from typing import List, Dict, Optional
from dataclasses import dataclass
from anthropic import Anthropic

# Import utilities from parent services directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from util import create_logger, ApolloError, sum_usage
from global_agent.config_loader import ConfigLoader
from global_agent.tools.tool_definitions import TOOL_DEFINITIONS
from tools.search_documentation.search_documentation import search_documentation_tool
from global_agent.subagent_caller import call_workflow_agent, format_subagent_result_for_llm

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
    """

    def __init__(self, config_loader: ConfigLoader, api_key: Optional[str] = None):
        """
        Initialize supervisor agent.

        Args:
            config_loader: Configuration loader instance
            api_key: Optional API key override
        """
        self.config = config_loader.config
        self.config_loader = config_loader
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        self.client = Anthropic(api_key=self.api_key)
        self.tools = TOOL_DEFINITIONS
        self.max_tool_calls = self.config.get("max_tool_calls", 10)

        # Track subagent calls
        self.subagent_results = []

        logger.info("SupervisorAgent initialized with tool-calling capability")

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
        Run the supervisor agent with tool-calling loop.

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
        logger.info("Supervisor.run() called")

        # Build system prompt
        system_prompt = self._build_system_prompt()

        # Build messages
        messages = history.copy() if history else []
        messages.append({"role": "user", "content": content})

        # Tool-calling loop
        tool_call_count = 0
        tool_calls_meta = []
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        while tool_call_count < self.max_tool_calls:
            try:
                response = self.client.messages.create(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                    system=system_prompt,
                    messages=messages,
                    tools=self.tools
                )

                # Track usage
                total_usage["input_tokens"] += response.usage.input_tokens
                total_usage["output_tokens"] += response.usage.output_tokens

                logger.info(f"Claude API call {tool_call_count + 1}: stop_reason={response.stop_reason}")

                # Check stop reason
                if response.stop_reason == "end_turn":
                    # Done - extract final response
                    final_text = self._extract_text(response)
                    final_yaml = self._get_yaml_from_subagents()

                    # Add final assistant message to messages
                    messages.append({
                        "role": "assistant",
                        "content": final_text
                    })

                    logger.info(f"Tool loop completed. Total calls: {tool_call_count}")
                    break

                elif response.stop_reason == "tool_use":
                    # Find tool use block
                    tool_use_block = self._find_tool_use(response.content)

                    if not tool_use_block:
                        logger.error("tool_use stop_reason but no tool_use block found")
                        break

                    logger.info(f"Executing tool: {tool_use_block.name}")

                    # Execute tool
                    if tool_use_block.name == "search_documentation":
                        tool_result = search_documentation_tool(tool_use_block.input)

                        tool_calls_meta.append({
                            "tool": "search_documentation",
                            "input": tool_use_block.input
                        })

                    elif tool_use_block.name == "call_workflow_agent":
                        subagent_result = call_workflow_agent(
                            tool_use_block.input,
                            existing_yaml=existing_yaml,
                            errors=errors,
                            history=messages,
                            read_only=read_only
                        )

                        # Aggregate subagent token usage into total
                        if "usage" in subagent_result:
                            total_usage = sum_usage(total_usage, subagent_result["usage"])

                        # Store subagent result
                        self.subagent_results.append(subagent_result)

                        # Format result for LLM
                        tool_result = format_subagent_result_for_llm(subagent_result)

                        tool_calls_meta.append({
                            "tool": "call_workflow_agent",
                            "input": tool_use_block.input
                        })

                    else:
                        logger.error(f"Unknown tool: {tool_use_block.name}")
                        tool_result = f"Error: Unknown tool {tool_use_block.name}"

                    # Add tool use and result to conversation
                    # Convert response.content to list of dicts for JSON serialization
                    content_blocks = []
                    for block in response.content:
                        if block.type == "text":
                            content_blocks.append({
                                "type": "text",
                                "text": block.text
                            })
                        elif block.type == "tool_use":
                            content_blocks.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input
                            })

                    messages.append({
                        "role": "assistant",
                        "content": content_blocks
                    })
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_block.id,
                            "content": tool_result
                        }]
                    })

                    tool_call_count += 1

                else:
                    logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                    break

            except Exception as e:
                logger.exception("Error in tool-calling loop")
                raise ApolloError(500, f"Tool execution error: {str(e)}")

        # If we exited loop without end_turn, extract final response from last message
        if response.stop_reason != "end_turn":
            final_text = self._extract_text(response)
            final_yaml = self._get_yaml_from_subagents()
            logger.warning(f"Loop exited without end_turn (reason: {response.stop_reason})")

        # Build result - don't add final_text again, it's already in messages
        result = SupervisorResult(
            response=final_text,
            response_yaml=final_yaml,
            history=messages,  # Changed: use messages directly
            usage=total_usage,
            meta={
                "iteration": 2,
                "tool_calls": tool_calls_meta,
                "subagent_calls": self.subagent_results,
                "total_tool_calls": tool_call_count
            }
        )

        logger.info(f"Supervisor completed. Tokens: {total_usage['input_tokens']} in, {total_usage['output_tokens']} out")
        return result

    def _find_tool_use(self, content):
        """Find tool_use block in response content."""
        for block in content:
            if block.type == "tool_use":
                return block
        return None

    def _extract_text(self, response):
        """Extract text from response content."""
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        return text

    def _get_yaml_from_subagents(self) -> Optional[str]:
        """
        Get YAML from subagent results.

        Returns the YAML from workflow_agent if it was called, else None.
        """
        for result in self.subagent_results:
            metadata = result.get("_call_metadata", {})
            if metadata.get("subagent") == "workflow_agent":
                return result.get("response_yaml")
        return None

    def _build_system_prompt(self) -> str:
        """Build system prompt for supervisor with tool descriptions."""
        return self.config_loader.get_prompt("supervisor_system_prompt")
