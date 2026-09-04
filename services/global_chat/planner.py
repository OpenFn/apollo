"""
Planner Agent - Coordinates tools and subagents for complex multi-step tasks.
"""

import os
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import httpx
from anthropic import Anthropic
import sentry_sdk

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from langfuse import observe
from util import create_logger, ApolloError, sum_usage
from streaming_util import (
    StreamManager,
    STATUS_REVIEWING_WORKFLOW,
    STATUS_NEW_WORKFLOW,
    STATUS_PLANNING,
)
from global_chat.config_loader import ConfigLoader
from models import resolve_model
from global_chat.tools.tool_definitions import TOOL_DEFINITIONS
from yaml_utils import stitch_job_code, redact_job_bodies, find_job_in_yaml, get_step_name_from_page, inspect_job_code
from tools.search_documentation.search_documentation import search_documentation_tool
from global_chat.subagent_caller import call_workflow_agent, call_job_agent, format_subagent_result_for_llm

logger = create_logger(__name__)

_FINAL_ROUND_NOTICE = (
    "Stop and reply to the user now. Say what you changed. Mention unfinished work "
    "only if there is any, and then offer to continue next turn — otherwise don't "
    "raise it at all."
)


@dataclass
class PlannerResult:
    """Result from planner run."""

    response: str
    response_segments: List[Dict]
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
        self.model = resolve_model(planner_config.get("model", "claude-opus"))
        self.max_tokens = planner_config.get("max_tokens", 24576)
        self.max_tool_calls = planner_config.get("max_tool_calls", 20)

        self.current_yaml: Optional[str] = None
        self.subagent_results = []
        self._segments: List[Dict] = []

        logger.info(f"PlannerAgent initialized with model: {self.model}")

    @observe(name="planner")
    def run(
        self,
        content: str,
        workflow_yaml: Optional[str],
        page: Optional[str],
        history: List[Dict],
        stream: bool,
        user: Optional[Dict] = None,
        metrics_opt_in: Optional[bool] = None,
        stream_manager: Optional[StreamManager] = None,
    ) -> PlannerResult:
        """
        Run the planner agent with tool-calling loop.

        Args:
            content: User message
            workflow_yaml: Full workflow YAML string (including job bodies)
            page: Current page URL (e.g. workflows/name/step-name)
            history: Conversation history
            stream: Whether to stream text via SSE events
            stream_manager: Optional shared stream manager from the router, so
                a handed-over request continues on the same stream

        Returns:
            PlannerResult with response, attachments, history, usage, meta
        """
        logger.info("Planner.run() called")

        stream_manager = stream_manager or StreamManager(model=self.model, stream=stream)
        if workflow_yaml:
            stream_manager.send_thinking(STATUS_REVIEWING_WORKFLOW + STATUS_PLANNING)
        else:
            stream_manager.send_thinking(STATUS_NEW_WORKFLOW + STATUS_PLANNING)

        self.current_yaml = workflow_yaml
        self.yaml_modified = False
        self._user = user
        self._metrics_opt_in = metrics_opt_in
        self._segments: List[Dict] = []

        stream_manager = StreamManager(model=self.model, stream=stream)
        if workflow_yaml:
            self._send_spinner(stream_manager, STATUS_REVIEWING_WORKFLOW + STATUS_PLANNING)
        else:
            self._send_spinner(stream_manager, STATUS_NEW_WORKFLOW + STATUS_PLANNING)

        system_prompt = self._build_system_prompt()

        messages = history.copy() if history else []

        messages.append({"role": "user", "content": self._build_user_content(content, page)})

        tool_call_count = 0
        tool_calls_meta = []
        total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

        try:
            # A run that spends its budget gets one more round with tools
            # switched off, so it ends on an answer rather than mid-narration.
            final_round = False
            while not final_round:
                final_round = tool_call_count >= self.max_tool_calls
                try:
                    response = self._call_api(
                        system_prompt,
                        messages,
                        stream,
                        stream_manager,
                        tool_choice={"type": "none"} if final_round else None,
                    )

                    for field in [
                        "input_tokens",
                        "output_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    ]:
                        total_usage[field] += getattr(response.usage, field, 0)

                    logger.info(f"Claude API call {tool_call_count + 1}: stop_reason={response.stop_reason}")

                    # Text from every round is part of the answer the user saw
                    # (tool rounds may narrate before calling tools).
                    round_text = self._extract_text(response)
                    if round_text:
                        self._segments.append({"type": "text", "content": round_text})

                    if response.stop_reason == "end_turn":
                        messages.append({"role": "assistant", "content": round_text})
                        logger.info(f"Tool loop completed. Total calls: {tool_call_count}")
                        break

                    elif response.stop_reason == "tool_use":
                        tool_use_blocks = self._find_all_tool_uses(response.content)

                        if not tool_use_blocks:
                            logger.error("tool_use stop_reason but no tool_use block found")
                            break

                        logger.info(f"Executing {len(tool_use_blocks)} tool(s): {[b.name for b in tool_use_blocks]}")

                        tool_results = self._execute_tool_blocks(
                            tool_use_blocks, stream_manager, total_usage, tool_calls_meta
                        )

                        content_blocks = []
                        for block in response.content:
                            if block.type == "thinking":
                                content_blocks.append({
                                    "type": "thinking",
                                    "thinking": block.thinking,
                                    "signature": block.signature,
                                })
                            elif block.type == "text":
                                content_blocks.append({"type": "text", "text": block.text})
                            elif block.type == "tool_use":
                                content_blocks.append(
                                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                                )

                        tool_call_count += len(tool_use_blocks)
                        if tool_call_count >= self.max_tool_calls:
                            tool_results.append({"type": "text", "text": _FINAL_ROUND_NOTICE})

                        messages.append({"role": "assistant", "content": content_blocks})
                        messages.append({"role": "user", "content": tool_results})

                    else:
                        logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                        break

                except ApolloError:
                    raise
                except Exception as e:
                    logger.exception("Error in tool-calling loop")
                    raise ApolloError(500, f"Tool execution error: {str(e)}")

            if response.stop_reason != "end_turn":
                logger.warning(f"Loop exited without end_turn (reason: {response.stop_reason})")
        finally:
            stream_manager.end_stream()

        # The full transcript in stream order: text segments (one per round)
        # interleaved with the status messages shown between them, so the
        # client can persist and re-render the woven view.
        response_segments = self._segments

        # response and history keep only the last round's text (the actual
        # answer), matching the direct routes and what was saved before
        # narration was streamed. The narration survives in response_segments.
        final_text = round_text

        if not final_text:
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "max_tokens":
                empty_reason = "max_tokens"
            elif stop_reason == "end_turn":
                empty_reason = "empty_final_round" if final_round else "no_text_blocks"
            else:
                empty_reason = f"unexpected_stop_reason:{stop_reason}"
            sentry_sdk.set_tag("stop_reason", stop_reason)
            sentry_sdk.set_tag("empty_reason", empty_reason)
            sentry_sdk.set_context("empty_response", {
                "service": "global_chat.planner",
                "tool_call_count": tool_call_count,
                "usage": total_usage,
            })
            if stop_reason == "max_tokens":
                raise ApolloError(502, f"Planner response truncated ({empty_reason})", type="OUTPUT_TRUNCATED")
            raise ApolloError(502, f"Planner produced no text ({empty_reason})", type="EMPTY_OUTPUT")

        agents_used = ["router", "planner"]
        for result in self.subagent_results:
            metadata = result.get("_call_metadata", {})
            subagent_name = metadata.get("subagent")
            if subagent_name and subagent_name not in agents_used:
                agents_used.append(subagent_name)

        attachments = []
        if self.yaml_modified and self.current_yaml:
            attachments.append({"type": "workflow_yaml", "content": self.current_yaml})

        # Return string-content history matching the direct routes, not the
        # internal block-format messages used by the tool-calling loop.
        return_history = (history.copy() if history else [])
        return_history.append({"role": "user", "content": content})
        return_history.append({"role": "assistant", "content": final_text})

        return PlannerResult(
            response=final_text,
            response_segments=response_segments,
            attachments=attachments,
            history=return_history,
            usage=total_usage,
            meta={
                "agents": agents_used,
                "planner_iterations": tool_call_count,
                "tool_calls": tool_calls_meta,
                "subagent_calls": self.subagent_results,
                "total_tool_calls": tool_call_count,
            },
        )

    def _build_user_content(self, content: str, page: Optional[str]) -> str:
        """Augment the user message with the step the user is viewing ("this step")
        and the existing workflow structure (bodies redacted)."""
        user_content = content

        if page:
            step_name = get_step_name_from_page(page)
            if step_name and self.current_yaml:
                matched_key, _ = find_job_in_yaml(self.current_yaml, step_name)
                step_name = matched_key or step_name
            if step_name:
                user_content += f"\n\n(The user is currently viewing the step '{step_name}'.)"
            else:
                user_content += f"\n\n(The user is currently viewing: {page})"

        if self.current_yaml:
            redacted = redact_job_bodies(self.current_yaml)
            user_content += f"\n\nExisting workflow structure (job code redacted):\n{redacted}"

        return user_content

    def _call_api(self, system_prompt, messages, stream, stream_manager, tool_choice=None):
        """Make Claude API call. When streaming, forwards text deltas live.

        All text blocks stream to the client as they generate — including the
        narration the model writes before tool calls. Each round's text lands
        in its own content block (the status and changes events sent between
        rounds close the open text block), so the client can weave text and
        status events with its own formatting.

        Adaptive thinking is enabled for better reasoning but thinking content
        is not streamed to the client — it exposes internal details like tool
        names and agent architecture. User-facing progress comes from the
        task-specific status messages sent before each tool execution.
        """
        choice = {"tool_choice": tool_choice} if tool_choice else {}

        if stream:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=self.tools,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                **choice,
            ) as stream_obj:
                for event in stream_obj:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        stream_manager.send_text(event.delta.text)
                return stream_obj.get_final_message()
        else:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
                tools=self.tools,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                **choice,
                # Per-request timeout (same values as the SDK default):
                # required for non-streaming calls with max_tokens > ~21k,
                # which the SDK otherwise rejects.
                timeout=httpx.Timeout(600.0, connect=5.0),
                betas=["context-management-2025-06-27"],
                # Sits above max_tool_calls on purpose. The budget already
                # bounds the conversation, so a trigger at the budget could
                # only ever fire on a round that overshoots it, which is the
                # wrap-up round. Clearing there deletes the edits the wrap-up
                # is being asked to describe, and `exclude_tools` means the
                # doc lookups are what survives. Headroom for a parallel
                # batch that overshoots, and `keep` covers a whole budget so
                # a run's own edits are never the thing cleared.
                context_management={
                    "edits": [
                        {
                            "type": "clear_tool_uses_20250919",
                            "trigger": {"type": "tool_uses", "value": 40},
                            "keep": {"type": "tool_uses", "value": 20},
                            "exclude_tools": ["search_documentation"],
                            "clear_tool_inputs": True,
                        }
                    ]
                },
            )
            return response

    def _send_yaml(self, stream_manager) -> None:
        """Stream the current YAML as a changes event.

        Called wherever the YAML is actually updated (workflow edit, job-code
        stitch), so each change reaches the client the moment it happens — e.g.
        a newly added step renders before its code is written. No-op in
        non-streaming mode, where the final payload's attachment carries the
        YAML instead.
        """
        stream_manager.send_changes({"yaml": self.current_yaml})

    def _send_spinner(self, stream_manager, status: str | list[str]) -> None:
        """Send a transient "...ing" spinner as a thinking event.

        Thinking events are live progress only: the client replaces each one
        with the next status and never persists them, so spinners are not
        recorded in the transcript.
        """
        stream_manager.send_thinking(status)

    def _send_settled(
        self,
        stream_manager,
        content: str | None,
        steps: list[dict] | None = None,
        summary: str | None = None,
    ) -> None:
        """Send a completed-action line ("Edited workflow structure") as a
        custom `status` event and record it in the transcript.

        Unlike spinners, these are durable facts about what happened: the
        client persists them (they resolve the preceding spinner), and they
        are recorded in `response_segments` so a page reload re-renders the
        same view. None means the action left nothing worth showing (e.g. a
        consult that changed nothing) — nothing is sent or recorded.

        `steps` carries which workflow steps this action touched, as data
        rather than as names buried in `content`, so a client can attach
        per-step detail without parsing the sentence. `summary` is the
        shorter line such a client shows instead, so names are not printed
        twice. Both are recorded alongside the segment so a reload has the
        same information the live stream did.
        """
        if not content:
            return
        stream_manager.send_status(content, steps=steps, summary=summary)

        segment = {"type": "status", "content": content}
        if steps:
            segment["steps"] = steps
        if summary:
            segment["summary"] = summary
        self._segments.append(segment)

    def _find_all_tool_uses(self, content):
        """Find all tool_use blocks in response content."""
        return [block for block in content if block.type == "tool_use"]

    def _execute_tool(self, tool_use_block, stream_manager, total_usage, tool_calls_meta) -> str:
        """Execute a single tool call and return the result string."""
        if tool_use_block.name == "search_documentation":
            tool_result = search_documentation_tool(tool_use_block.input)

            tool_calls_meta.append({"tool": "search_documentation", "input": tool_use_block.input})

        elif tool_use_block.name == "call_workflow_agent":
            try:
                subagent_result = call_workflow_agent(
                    tool_use_block.input,
                    workflow_yaml=self.current_yaml,
                    api_key=self.api_key,
                    user=self._user,
                    metrics_opt_in=self._metrics_opt_in,
                )
            except Exception as e:
                logger.exception("call_workflow_agent failed")
                tool_calls_meta.append({"tool": "call_workflow_agent", "input": tool_use_block.input, "error": str(e)})
                return f"ERROR: The workflow agent failed: {e}. The workflow was not changed."

            if "usage" in subagent_result:
                total_usage.update(sum_usage(total_usage, subagent_result["usage"]))

            # Update live state and stream the change in the same breath
            if subagent_result.get("response_yaml"):
                self.current_yaml = subagent_result["response_yaml"]
                self.yaml_modified = True
                self._send_yaml(stream_manager)

            self.subagent_results.append(subagent_result)

            tool_result = format_subagent_result_for_llm(subagent_result)

            # Give planner a fresh structural view after each workflow change.
            # If no YAML came back, nothing changed — say so instead of re-sending
            # the unchanged structure (a conversational reply or a failed YAML
            # parse would otherwise read as a successful edit).
            if subagent_result.get("response_yaml"):
                redacted = redact_job_bodies(self.current_yaml)
                tool_result += f"\n\nUpdated workflow structure:\n{redacted}"
            else:
                tool_result += "\n\n[No workflow changes were made — no YAML was produced.]"

            tool_calls_meta.append({"tool": "call_workflow_agent", "input": tool_use_block.input})

        elif tool_use_block.name == "call_job_code_agent":
            job_key = tool_use_block.input.get("job_key")

            # Guard: workflow must exist and contain the target job
            if not self.current_yaml:
                tool_result = "ERROR: No workflow exists yet. Call call_workflow_agent first to create the workflow, then call call_job_code_agent."
                tool_calls_meta.append({"tool": "call_job_code_agent", "input": tool_use_block.input, "skipped": True})
                return tool_result
            matched_job_key = None
            if job_key:
                matched_job_key, job_data = find_job_in_yaml(self.current_yaml, job_key)
                if not job_data:
                    tool_result = f"ERROR: Job key '{job_key}' not found in workflow YAML. Create the workflow with this job first."
                    tool_calls_meta.append(
                        {"tool": "call_job_code_agent", "input": tool_use_block.input, "skipped": True}
                    )
                    return tool_result

            try:
                subagent_result = call_job_agent(
                    tool_use_block.input,
                    workflow_yaml=self.current_yaml,
                    api_key=self.api_key,
                    user=self._user,
                    metrics_opt_in=self._metrics_opt_in,
                )
            except Exception as e:
                logger.exception("call_job_code_agent failed")
                tool_calls_meta.append({"tool": "call_job_code_agent", "input": tool_use_block.input, "error": str(e)})
                return f"ERROR: The job code agent failed: {e}. No code was generated for this job."

            if "usage" in subagent_result:
                total_usage.update(sum_usage(total_usage, subagent_result["usage"]))

            # Stitch code into live state immediately. Use the YAML key returned by
            # find_job_in_yaml — `job_key` from the planner may be a fuzzy variant
            # (case, hyphens vs underscores, or the job's name field), and
            # stitch_job_code does an exact key match.
            suggested_code = subagent_result.get("suggested_code")
            stitched = False
            if matched_job_key and suggested_code and self.current_yaml:
                self.current_yaml = stitch_job_code(self.current_yaml, matched_job_key, suggested_code)
                self.yaml_modified = True
                stitched = True
                self._send_yaml(stream_manager)
                logger.info(f"Stitched code for job '{matched_job_key}' into current_yaml")

            self.subagent_results.append(subagent_result)
            tool_result = format_subagent_result_for_llm(subagent_result)
            if stitched:
                tool_result += "\n\n[Job code generated and stitched into the workflow.]"
            elif suggested_code:
                tool_result += "\n\n[Job code was generated but NOT added to the workflow — no job_key matched. Retry with the exact job key.]"
            else:
                tool_result += "\n\n[No job code was generated.]"

            tool_calls_meta.append({"tool": "call_job_code_agent", "input": tool_use_block.input})

        elif tool_use_block.name == "inspect_job_code":
            # Accept job_keys (list); tolerate legacy single job_key
            job_keys = tool_use_block.input.get("job_keys") or []
            single_key = tool_use_block.input.get("job_key")
            if single_key:
                job_keys.append(single_key)

            tool_result = inspect_job_code(self.current_yaml, job_keys)

            tool_calls_meta.append({"tool": "inspect_job_code", "input": tool_use_block.input})

        else:
            logger.error(f"Unknown tool: {tool_use_block.name}")
            tool_result = f"Error: Unknown tool {tool_use_block.name}"

        return tool_result

    def _execute_tool_blocks(self, tool_use_blocks, stream_manager, total_usage, tool_calls_meta):
        """Run a batch of tool_use blocks in a deliberate order and collect results.

        Ordering is load-bearing: workflow-structure tools (and any other
        non-job tools) run FIRST and mutate ``self.current_yaml``, then the
        job-code tools run against that updated YAML. The prompt tells the
        planner never to mix call_workflow_agent and call_job_code_agent in one
        step, but if it does anyway, this order is what keeps job code stitched
        into the freshly-modified workflow rather than a stale snapshot.
        """
        job_code_blocks = [b for b in tool_use_blocks if b.name == "call_job_code_agent"]
        other_blocks = [b for b in tool_use_blocks if b.name != "call_job_code_agent"]

        tool_results = []

        for tool_use_block in other_blocks:
            self._send_spinner(stream_manager, self._tool_status_message(tool_use_block))
            yaml_before = self.current_yaml
            tool_result = self._execute_tool(tool_use_block, stream_manager, total_usage, tool_calls_meta)
            self._send_settled(stream_manager, self._settled_status_message(tool_use_block, yaml_before))
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tool_use_block.id, "content": tool_result}
            )

        if job_code_blocks:
            job_results = self._execute_job_code_tools_parallel(
                job_code_blocks, stream_manager, total_usage, tool_calls_meta
            )
            tool_results.extend(job_results)

        return tool_results

    def _execute_job_code_tools_parallel(self, blocks, stream_manager, total_usage, tool_calls_meta):
        """Execute multiple call_job_code_agent tools with parallel API calls.

        Sends all status messages up front, runs the slow subagent calls
        concurrently, then stitches results into the YAML sequentially.
        """
        # Send a combined status message for all job code steps
        names = [self._display_name_for_job(b.input.get("job_key")) for b in blocks]
        names = [n for n in names if n]
        if names:
            joined = ", ".join(f"\"{n}\"" for n in names)
            status = f"Writing code for {joined}..."
        else:
            status = "Writing job code..."
        self._send_spinner(stream_manager, status)

        # Validate and prepare — skip invalid ones before launching threads.
        # matched_keys carries the YAML key resolved by find_job_in_yaml's
        # fuzzy match; stitch_job_code below requires the exact key.
        to_run = []
        skipped = {}
        matched_keys: dict[str, str] = {}
        for block in blocks:
            job_key = block.input.get("job_key")
            if not self.current_yaml:
                skipped[block.id] = "ERROR: No workflow exists yet. Call call_workflow_agent first to create the workflow, then call call_job_code_agent."
                tool_calls_meta.append({"tool": "call_job_code_agent", "input": block.input, "skipped": True})
            elif job_key:
                matched_job_key, job_data = find_job_in_yaml(self.current_yaml, job_key)
                if not job_data:
                    skipped[block.id] = f"ERROR: Job key '{job_key}' not found in workflow YAML. Create the workflow with this job first."
                    tool_calls_meta.append({"tool": "call_job_code_agent", "input": block.input, "skipped": True})
                else:
                    matched_keys[block.id] = matched_job_key
                    to_run.append(block)
            else:
                to_run.append(block)

        # Run subagent API calls in parallel (the slow part)
        parallel_results = {}
        if len(to_run) > 1:
            with ThreadPoolExecutor(max_workers=len(to_run)) as executor:
                futures = {
                    executor.submit(
                        call_job_agent,
                        block.input,
                        self.current_yaml,
                        self.api_key,
                        self._user,
                        self._metrics_opt_in,
                    ): block
                    for block in to_run
                }
                for future in as_completed(futures):
                    block = futures[future]
                    try:
                        parallel_results[block.id] = future.result()
                    except Exception as e:
                        logger.exception("call_job_code_agent failed")
                        parallel_results[block.id] = {"_error": str(e)}
        elif to_run:
            block = to_run[0]
            try:
                parallel_results[block.id] = call_job_agent(
                    block.input,
                    self.current_yaml,
                    self.api_key,
                    self._user,
                    self._metrics_opt_in,
                )
            except Exception as e:
                logger.exception("call_job_code_agent failed")
                parallel_results[block.id] = {"_error": str(e)}

        # Stitch results and update state sequentially
        tool_results = []
        stitched_steps = []
        for block in blocks:
            if block.id in skipped:
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": skipped[block.id]}
                )
                continue

            subagent_result = parallel_results[block.id]
            if "_error" in subagent_result:
                tool_calls_meta.append({"tool": "call_job_code_agent", "input": block.input, "error": subagent_result["_error"]})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"ERROR: The job code agent failed: {subagent_result['_error']}. No code was generated for this job.",
                })
                continue
            matched_job_key = matched_keys.get(block.id)

            if "usage" in subagent_result:
                total_usage.update(sum_usage(total_usage, subagent_result["usage"]))

            suggested_code = subagent_result.get("suggested_code")
            stitched = False
            if matched_job_key and suggested_code and self.current_yaml:
                self.current_yaml = stitch_job_code(self.current_yaml, matched_job_key, suggested_code)
                self.yaml_modified = True
                stitched = True
                stitched_steps.append(
                    {
                        "key": matched_job_key,
                        "name": self._display_name_for_job(matched_job_key),
                    },
                )
                logger.info(f"Stitched code for job '{matched_job_key}' into current_yaml")

            self.subagent_results.append(subagent_result)
            tool_result = format_subagent_result_for_llm(subagent_result)
            if stitched:
                tool_result += "\n\n[Job code generated and stitched into the workflow.]"
            elif suggested_code:
                tool_result += "\n\n[Job code was generated but NOT added to the workflow — no job_key matched. Retry with the exact job key.]"
            else:
                tool_result += "\n\n[No job code was generated.]"

            tool_calls_meta.append({"tool": "call_job_code_agent", "input": block.input})
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": tool_result}
            )

        # Settle the spinner with the steps that were actually applied (drop any
        # that failed to stitch); nothing sent if none applied. One YAML send
        # covers the whole batch, mirroring the one combined status.
        if stitched_steps:
            self._send_yaml(stream_manager)
            joined = ", ".join(f"\"{step['name']}\"" for step in stitched_steps)
            count = len(stitched_steps)
            self._send_settled(
                stream_manager,
                f"Wrote code for {joined}",
                steps=stitched_steps,
                # Clients that render a block per step get the count instead,
                # so the names appear once, on the blocks.
                summary=f"Wrote code for {count} step{'' if count == 1 else 's'}",
            )

        return tool_results

    def _tool_status_message(self, tool_use_block) -> str:
        """Generate a user-facing status message for a tool call."""
        name = tool_use_block.name
        inputs = tool_use_block.input or {}

        if name == "search_documentation":
            query = inputs.get("query", "")
            if query:
                return f"Searching documentation for \"{query}\"..."
            return "Searching documentation..."

        if name == "call_workflow_agent":
            if self.current_yaml:
                return "Reviewing the workflow..."
            return "Building workflow outline..."

        if name == "call_job_code_agent":
            job_key = inputs.get("job_key")
            display_name = self._display_name_for_job(job_key)
            if display_name:
                return f"Writing code for \"{display_name}\"..."
            return "Writing job code..."

        if name == "inspect_job_code":
            job_keys = inputs.get("job_keys") or ([inputs["job_key"]] if inputs.get("job_key") else [])
            display_names = [n for n in (self._display_name_for_job(k) for k in job_keys) if n]
            if display_names:
                joined = ", ".join(f"\"{n}\"" for n in display_names)
                return f"Reading code for {joined}..."
            return "Reading job code..."

        return f"Running {name}..."

    def _settled_status_message(self, tool_use_block, yaml_before: str | None) -> str | None:
        """Past-tense line that resolves the spinner for a finished tool call.

        Counterpart to _tool_status_message. For workflow edits the outcome is
        read from whether the YAML actually changed: an unchanged workflow means
        the agent only advised (or errored), so it settles to "Analyzed the
        workflow" rather than claiming an edit. Returns None when there's
        nothing worth persisting. Job-code settling is handled where the code is
        stitched, since it depends on which steps were applied.
        """
        name = tool_use_block.name
        inputs = tool_use_block.input or {}

        if name == "call_workflow_agent":
            if self.current_yaml == yaml_before:
                return "Analyzed the workflow"
            return "Edited workflow structure" if yaml_before else "Built workflow outline"

        if name == "search_documentation":
            query = inputs.get("query")
            return f"Searched documentation for \"{query}\"" if query else "Searched documentation"

        if name == "inspect_job_code":
            job_keys = inputs.get("job_keys") or ([inputs["job_key"]] if inputs.get("job_key") else [])
            names = [n for n in (self._display_name_for_job(k) for k in job_keys) if n]
            if names:
                joined = ", ".join(f"\"{n}\"" for n in names)
                return f"Read code for {joined}"
            return "Read code"

        return None

    def _display_name_for_job(self, job_key: str | None) -> str | None:
        """Look up a human-readable display name for a job key.

        Returns the workflow YAML's own name for the job when it has one,
        otherwise title-cases the key (e.g. "fetch-patients" -> "Fetch
        Patients").
        """
        if not job_key:
            return None

        if self.current_yaml:
            _, job_data = find_job_in_yaml(self.current_yaml, job_key)
            if job_data and job_data.get("name"):
                # The user named this step; use it verbatim. Title-casing it
                # renames "Transform data" to "Transform Data" in the prose,
                # which then disagrees with the name shown everywhere else
                # in the UI.
                return job_data["name"]

        return self._format_display_name(job_key)

    @staticmethod
    def _format_display_name(name: str) -> str:
        """Format a job key or name into readable title case."""
        return name.replace("-", " ").replace("_", " ").title()

    def _extract_text(self, response):
        """Extract text from response content, concatenated as it was streamed."""
        return "".join(block.text for block in response.content if block.type == "text")

    def _build_system_prompt(self) -> list:
        """Build system prompt for planner with cache control."""
        prompt_text = self.config_loader.get_prompt("planner_system_prompt")

        return [{"type": "text", "text": prompt_text, "cache_control": {"type": "ephemeral"}}]
