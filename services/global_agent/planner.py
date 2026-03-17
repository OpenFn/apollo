"""
Planner Agent - Coordinates tools and subagents for complex multi-step tasks.
"""
import os
from typing import List, Dict, Optional
from dataclasses import dataclass
from anthropic import Anthropic

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from util import create_logger, ApolloError, sum_usage
from streaming_util import StreamManager
from global_agent.config_loader import ConfigLoader
from global_agent.tools.tool_definitions import TOOL_DEFINITIONS
from global_agent.yaml_utils import stitch_job_code, redact_job_bodies, find_job_in_yaml
from tools.search_documentation.search_documentation import search_documentation_tool
from global_agent.subagent_caller import call_workflow_agent, call_job_agent, format_subagent_result_for_llm

logger = create_logger(__name__)


@dataclass
class PlannerResult:
    """Result from planner run."""
    response: str
    attachments: List[Dict]
    history: List[Dict]
    usage: Dict
    meta: Dict


class PlannerAgent:
    """
    Planner agent that coordinates subagents and tools for complex multi-step tasks.
    """

    def __init__(self, config_loader: ConfigLoader, api_key: Optional[str] = None):
        self.config_loader = config_loader
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ApolloError(500, "ANTHROPIC_API_KEY not found")

        self.client = Anthropic(api_key=self.api_key)
        self.tools = TOOL_DEFINITIONS

        planner_config = config_loader.config.get("planner", {})
        self.model = planner_config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = planner_config.get("max_tokens", 8192)
        self.temperature = planner_config.get("temperature", 1.0)
        self.max_tool_calls = planner_config.get("max_tool_calls", 10)

        self.current_yaml: Optional[str] = None
        self.subagent_results = []

        logger.info(f"PlannerAgent initialized with model: {self.model}")

    def run(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool
    ) -> PlannerResult:
        """
        Run the planner agent with tool-calling loop.

        Args:
            content: User message
            workflow_yaml: Full workflow YAML string (including job bodies)
            page: Current page URL (e.g. workflows/name/step-name)
            history: Conversation history
            stream: Streaming flag (not implemented)

        Returns:
            PlannerResult with response, attachments, history, usage, meta
        """
        logger.info("Planner.run() called")

        stream_manager = StreamManager(model=self.model, stream=stream)
        stream_manager.send_thinking("Analyzing request...")

        self.current_yaml = workflow_yaml

        system_prompt = self._build_system_prompt()

        messages = history.copy() if history else []

        # Give planner visibility into existing workflow structure (bodies redacted)
        user_content = content
        if self.current_yaml:
            redacted = redact_job_bodies(self.current_yaml)
            user_content = f"{content}\n\nExisting workflow structure (job code redacted):\n{redacted}"

        messages.append({"role": "user", "content": user_content})

        tool_call_count = 0
        tool_calls_meta = []
        total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }

        final_text = ""

        while tool_call_count < self.max_tool_calls:
            try:
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    messages=messages,
                    tools=self.tools,
                    betas=["context-management-2025-06-27"],
                    context_management={
                        "edits": [
                            {
                                "type": "clear_tool_uses_20250919",
                                "trigger": {
                                    "type": "tool_uses",
                                    "value": 3
                                },
                                "keep": {
                                    "type": "tool_uses",
                                    "value": 2
                                },
                                "exclude_tools": ["search_documentation"],
                                "clear_tool_inputs": True
                            }
                        ]
                    }
                )

                for field in ["input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"]:
                    total_usage[field] += getattr(response.usage, field, 0)

                logger.info(f"Claude API call {tool_call_count + 1}: stop_reason={response.stop_reason}")

                if response.stop_reason == "end_turn":
                    if tool_call_count > 0:
                        stream_manager.send_thinking("Collating components...")
                    final_text = self._extract_text(response)
                    messages.append({
                        "role": "assistant",
                        "content": final_text
                    })
                    logger.info(f"Tool loop completed. Total calls: {tool_call_count}")
                    break

                elif response.stop_reason == "tool_use":
                    tool_use_blocks = self._find_all_tool_uses(response.content)

                    if not tool_use_blocks:
                        logger.error("tool_use stop_reason but no tool_use block found")
                        break

                    logger.info(f"Executing {len(tool_use_blocks)} tool(s): {[b.name for b in tool_use_blocks]}")

                    tool_results = []
                    for tool_use_block in tool_use_blocks:
                        tool_result = self._execute_tool(tool_use_block, total_usage, tool_calls_meta)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_block.id,
                            "content": tool_result
                        })

                    content_blocks = []
                    for block in response.content:
                        if block.type == "text":
                            content_blocks.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            content_blocks.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": block.input
                            })

                    messages.append({"role": "assistant", "content": content_blocks})
                    messages.append({"role": "user", "content": tool_results})

                    tool_call_count += len(tool_use_blocks)

                else:
                    logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                    break

            except Exception as e:
                logger.exception("Error in tool-calling loop")
                raise ApolloError(500, f"Tool execution error: {str(e)}")

        if response.stop_reason != "end_turn":
            final_text = self._extract_text(response)
            logger.warning(f"Loop exited without end_turn (reason: {response.stop_reason})")

        agents_used = ["router", "planner"]
        for result in self.subagent_results:
            metadata = result.get("_call_metadata", {})
            subagent_name = metadata.get("subagent")
            if subagent_name and subagent_name not in agents_used:
                agents_used.append(subagent_name)

        attachments = []
        if self.current_yaml:
            attachments.append({"type": "workflow_yaml", "content": self.current_yaml})

        return PlannerResult(
            response=final_text,
            attachments=attachments,
            history=messages,
            usage=total_usage,
            meta={
                "agents": agents_used,
                "planner_iterations": tool_call_count,
                "tool_calls": tool_calls_meta,
                "subagent_calls": self.subagent_results,
                "total_tool_calls": tool_call_count
            }
        )

    def _find_all_tool_uses(self, content):
        """Find all tool_use blocks in response content."""
        return [block for block in content if block.type == "tool_use"]

    def _execute_tool(self, tool_use_block, total_usage, tool_calls_meta) -> str:
        """Execute a single tool call and return the result string."""
        if tool_use_block.name == "search_documentation":
            tool_result = search_documentation_tool(tool_use_block.input)

            tool_calls_meta.append({
                "tool": "search_documentation",
                "input": tool_use_block.input
            })

        elif tool_use_block.name == "call_workflow_agent":
            subagent_result = call_workflow_agent(
                tool_use_block.input,
                workflow_yaml=self.current_yaml
            )

            if "usage" in subagent_result:
                total_usage.update(sum_usage(total_usage, subagent_result["usage"]))

            # Update live state eagerly
            if subagent_result.get("response_yaml"):
                self.current_yaml = subagent_result["response_yaml"]

            self.subagent_results.append(subagent_result)

            tool_result = format_subagent_result_for_llm(subagent_result)

            # Give planner a fresh structural view after each workflow change
            if self.current_yaml:
                redacted = redact_job_bodies(self.current_yaml)
                tool_result += f"\n\nUpdated workflow structure:\n{redacted}"

            tool_calls_meta.append({
                "tool": "call_workflow_agent",
                "input": tool_use_block.input
            })

        elif tool_use_block.name == "call_job_code_agent":
            subagent_result = call_job_agent(
                tool_use_block.input,
                workflow_yaml=self.current_yaml
            )

            if "usage" in subagent_result:
                total_usage.update(sum_usage(total_usage, subagent_result["usage"]))

            # Stitch code into live state immediately
            job_key = tool_use_block.input.get("job_key")
            suggested_code = subagent_result.get("suggested_code")
            if job_key and suggested_code and self.current_yaml:
                self.current_yaml = stitch_job_code(self.current_yaml, job_key, suggested_code)
                logger.info(f"Stitched code for job '{job_key}' into current_yaml")

            self.subagent_results.append(subagent_result)
            tool_result = format_subagent_result_for_llm(subagent_result)
            if suggested_code:
                tool_result += "\n\n[Job code generated and stitched into the workflow.]"
            else:
                tool_result += "\n\n[No job code was generated.]"

            tool_calls_meta.append({
                "tool": "call_job_code_agent",
                "input": tool_use_block.input
            })

        elif tool_use_block.name == "inspect_job_code":
            job_key = tool_use_block.input.get("job_key")
            if not self.current_yaml:
                tool_result = "No workflow available to inspect."
            else:
                _, job_data = find_job_in_yaml(self.current_yaml, job_key)
                if job_data and job_data.get("body"):
                    tool_result = f"Job code for '{job_key}':\n\n{job_data['body']}"
                else:
                    tool_result = f"No code found for job '{job_key}'."

            tool_calls_meta.append({
                "tool": "inspect_job_code",
                "input": tool_use_block.input
            })

        else:
            logger.error(f"Unknown tool: {tool_use_block.name}")
            tool_result = f"Error: Unknown tool {tool_use_block.name}"

        return tool_result

    def _extract_text(self, response):
        """Extract text from response content."""
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        return text

    def _build_system_prompt(self) -> list:
        """Build system prompt for planner with cache control."""
        prompt_text = self.config_loader.get_prompt("planner_system_prompt")

        return [
            {
                "type": "text",
                "text": prompt_text,
                "cache_control": {"type": "ephemeral"}
            }
        ]
