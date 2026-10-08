"""Unit tests for skills handed to job_chat by its caller.

The caller passes the skills written for this agent; job_chat offers them
through a load_skill tool, and loading one returns its instructions and lets
the model carry on, the same way reading another step does.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from job_chat.job_chat import AnthropicClient, ChatConfig

SKILLS = [{"name": "qa-code", "description": "Review one step", "body": "Check the loops."}]


def tool_use(name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"tu_{name}", name=name, input=tool_input)


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def message(*blocks: SimpleNamespace) -> SimpleNamespace:
    usage = MagicMock()
    usage.model_dump.return_value = {"input_tokens": 1, "output_tokens": 1}
    usage.cache_creation_input_tokens = 0
    usage.cache_read_input_tokens = 0
    return SimpleNamespace(content=list(blocks), usage=usage, stop_reason="end_turn")


def run(responses: list, skills: list | None) -> MagicMock:
    with patch("job_chat.job_chat.Anthropic"):
        client = AnthropicClient(ChatConfig(api_key="test"))
    client.client.messages.create.side_effect = responses
    with patch("job_chat.job_chat.build_prompt", return_value=("system", [{"role": "user", "content": "hi"}], {})):
        client.generate(content="is this ready?", suggest_code=True, subagent=True, skills=skills)
    return client.client.messages.create


def test_given_skills_are_offered_as_a_load_skill_tool() -> None:
    create = run([message(text("Looks fine."))], SKILLS)

    tools = {t["name"]: t for t in create.call_args.kwargs["tools"]}
    assert tools["load_skill"]["input_schema"]["properties"]["name"]["enum"] == ["qa-code"]
    assert "- qa-code: Review one step" in tools["load_skill"]["description"]


def test_without_skills_there_is_no_load_skill_tool() -> None:
    create = run([message(text("Looks fine."))], None)

    assert "load_skill" not in [t["name"] for t in create.call_args.kwargs["tools"]]


def test_loading_a_skill_returns_its_instructions_and_continues() -> None:
    create = run(
        [message(tool_use("load_skill", {"name": "qa-code"})), message(text("Reviewed."))],
        SKILLS,
    )

    tool_result = create.call_args.kwargs["messages"][-1]["content"][0]
    assert tool_result["content"] == "Check the loops."
