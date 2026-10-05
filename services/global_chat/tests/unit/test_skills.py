"""Unit tests for skill invocation.

A slash command states the intent the router would otherwise guess, so an
invoked skill skips the routing call and goes to the planner. The skill's
instructions are per-turn context, like attachments: the model sees them, the
returned history does not.

Apollo never parses commands out of free text — the client recognises the
command and names it in the payload — so a message that merely mentions a
slash command routes normally.
"""

from unittest.mock import patch

import pytest
from global_chat.global_chat import Payload
from global_chat.planner import PlannerResult
from global_chat.router import RouterAgent, RouterDecision, RouterResult
from global_chat.skill_registry import SKILLS, get_skill, strip_invocation
from global_chat.tools.tool_definitions import LOAD_SKILL_TOOL
from util import ApolloError

from streaming_util import STATUS_NEW_WORKFLOW, STATUS_PLANNING

from .test_planner import (
    FakeResponse,
    FakeText,
    FakeToolUse,
    StubStreamManager,
    empty_usage,
    make_planner,
)
from .test_router import make_router


# --- the registry ---------------------------------------------------------


def test_the_two_standard_skills_are_loaded() -> None:
    assert {"diagnose", "qa"} <= set(SKILLS)


def test_every_skill_declares_the_name_it_is_invoked_by() -> None:
    """A frontmatter name that disagrees with its folder is unreachable."""
    for name, skill in SKILLS.items():
        assert skill.name == name
        assert skill.description
        assert skill.body


def test_an_unknown_skill_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ApolloError) as excinfo:
        get_skill("sudo")

    assert excinfo.value.code == 400
    assert excinfo.value.type == "UNKNOWN_SKILL"
    assert "diagnose" in excinfo.value.details["available"]


# --- the payload field ----------------------------------------------------


def test_a_named_skill_arrives_resolved() -> None:
    payload = Payload.from_dict({"content": "/qa", "skill": {"name": "qa"}})

    assert payload.skill.body == get_skill("qa").body


def test_a_skill_that_is_not_an_object_with_a_name_is_rejected() -> None:
    with pytest.raises(ApolloError) as excinfo:
        Payload.from_dict({"content": "hi", "skill": "qa"})

    assert excinfo.value.code == 400


def test_no_skill_field_is_the_unchanged_payload() -> None:
    assert Payload.from_dict({"content": "hi"}).skill is None


# --- stripping the command token ------------------------------------------


def test_the_command_token_goes_and_the_request_stays() -> None:
    assert strip_invocation("/diagnose why did this fail?", "diagnose") == "why did this fail?"


def test_a_bare_command_leaves_no_request() -> None:
    assert strip_invocation("/qa", "qa") == ""


def test_a_command_token_is_only_stripped_at_the_start() -> None:
    assert strip_invocation("tell me what /qa does", "qa") == "tell me what /qa does"


def test_a_longer_word_starting_with_the_name_is_not_the_command() -> None:
    assert strip_invocation("/qa-checklist please", "qa") == "/qa-checklist please"


# --- the bypass -----------------------------------------------------------


def stub_planner(captured: dict) -> type:
    """A PlannerAgent that records the call instead of making one."""

    class StubPlanner:
        def __init__(self, *_args: object) -> None:
            pass

        def run(self, **kwargs: object) -> PlannerResult:
            captured.update(kwargs)
            return PlannerResult(
                response="done",
                response_segments=[],
                attachments=[],
                history=[],
                usage=empty_usage(),
                meta={"agents": ["router", "planner"], "planner_iterations": 0},
            )

    return StubPlanner


def invoke_skill(name: str, content: str) -> tuple[dict, RouterResult]:
    router = make_router()
    router.config_loader = None
    captured: dict = {}

    with patch("global_chat.planner.PlannerAgent", stub_planner(captured)), \
         patch.object(RouterAgent, "_make_routing_decision") as decision:
        result = router.route_and_execute(
            content=content,
            workflow_yaml=None,
            page=None,
            history=[],
            stream=False,
            skill=get_skill(name),
        )

    assert decision.call_count == 0
    return captured, result


def test_an_invoked_skill_never_pays_for_a_routing_call() -> None:
    captured, result = invoke_skill("diagnose", "/diagnose why did this fail?")

    assert captured["skill"].name == "diagnose"
    assert result.meta["skill"] == "diagnose"
    # The router did not run, so it has neither a place in the path nor a
    # confidence to report.
    assert "router" not in result.meta["agents"]
    assert "router_confidence" not in result.meta


def test_the_planner_is_asked_what_the_user_asked_not_the_command() -> None:
    captured, _ = invoke_skill("diagnose", "/diagnose why did this fail?")

    assert captured["content"] == "why did this fail?"


def test_a_message_that_only_mentions_a_command_is_routed_normally() -> None:
    router = make_router()
    router.config_loader = None
    captured: dict = {}

    with patch("global_chat.planner.PlannerAgent", stub_planner(captured)), \
         patch.object(
             RouterAgent,
             "_make_routing_decision",
             return_value=RouterDecision(destination="planner", confidence=4),
         ) as decision:
        result = router.route_and_execute(
            content="/qa looks odd on this workflow",
            workflow_yaml=None,
            page=None,
            history=[],
            stream=False,
        )

    assert decision.call_count == 1
    assert captured["skill"] is None
    assert captured["content"] == "/qa looks odd on this workflow"
    assert result.meta["router_confidence"] == 4


# --- injection into the turn ----------------------------------------------


def test_the_skill_instructions_lead_the_turn_the_model_sees() -> None:
    planner = make_planner()
    planner._skill = get_skill("qa")

    user_content = planner._build_user_content("check this", None)

    assert user_content.startswith('<skill name="qa">')
    assert get_skill("qa").body in user_content
    assert "check this" in user_content


def test_a_bare_invocation_still_carries_the_instructions() -> None:
    planner = make_planner()
    planner._skill = get_skill("qa")

    assert get_skill("qa").body in planner._build_user_content("", None)


def test_the_skill_body_is_not_replayed_on_later_turns() -> None:
    """Like an attachment: the model sees it this turn, history keeps the words
    the user typed. The client re-sends `skill` on each turn it applies to."""
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 1
    seen: list = []

    def fake_api(_system: object, messages: list, *_args: object, **_kwargs: object) -> FakeResponse:
        # Copied: run() appends the reply to this same list afterwards.
        seen.append(list(messages))
        return FakeResponse("end_turn", [FakeText("here is the review")])

    with patch.object(planner, "_call_api", side_effect=fake_api), \
         patch.object(planner, "_build_system_prompt", return_value="sys"):
        result = planner.run(
            content="check this",
            workflow_yaml=None,
            page=None,
            history=[],
            stream=False,
            skill=get_skill("qa"),
        )

    body = get_skill("qa").body
    assert body in seen[0][-1]["content"]
    assert [turn["content"] for turn in result.history] == ["check this", "here is the review"]


# --- telling the user a skill is running ----------------------------------


def run_turn(skill_name: str | None) -> tuple[StubStreamManager, object]:
    """One planner turn that answers immediately, on a recording stream."""
    planner = make_planner()
    planner.model = "test-model"
    planner.max_tool_calls = 1
    stream_manager = StubStreamManager()

    with patch.object(planner, "_call_api", return_value=FakeResponse("end_turn", [FakeText("done")])), \
         patch.object(planner, "_build_system_prompt", return_value="sys"):
        result = planner.run(
            content="check this",
            workflow_yaml=None,
            page=None,
            history=[],
            stream=False,
            stream_manager=stream_manager,
            skill=get_skill(skill_name) if skill_name else None,
        )

    return stream_manager, result


def test_a_skill_turn_opens_by_naming_the_skill() -> None:
    stream_manager, _ = run_turn("qa")

    assert stream_manager.thinking == ["Running the /qa skill..."]


def test_a_skill_turn_settles_where_it_was_announced() -> None:
    """Durable, and first: the invocation happens at the top of the turn, so
    the settled line stays above the answer rather than trailing it."""
    _, result = run_turn("qa")

    assert result.response_segments[0] == {"type": "status", "content": "Ran the /qa skill"}


def test_a_turn_without_a_skill_opens_and_settles_as_before() -> None:
    stream_manager, result = run_turn(None)

    assert stream_manager.thinking == [STATUS_NEW_WORKFLOW + STATUS_PLANNING]
    assert [segment["type"] for segment in result.response_segments] == ["text"]


# --- the planner loading a skill itself -----------------------------------


def test_the_load_skill_tool_offers_every_registered_skill() -> None:
    assert LOAD_SKILL_TOOL["input_schema"]["properties"]["name"]["enum"] == sorted(SKILLS)
    for skill in SKILLS.values():
        assert f"- {skill.name}: {skill.description}" in LOAD_SKILL_TOOL["description"]


def test_loading_a_skill_returns_its_instructions() -> None:
    planner = make_planner()
    stream_manager = StubStreamManager()

    results = planner._execute_tool_blocks(
        [FakeToolUse("load_skill", {"name": "qa"})], stream_manager, empty_usage(), [],
    )

    assert results[0]["content"] == get_skill("qa").body
    assert stream_manager.thinking == ["Running the /qa skill..."]
    assert stream_manager.statuses[0]["content"] == "Ran the /qa skill"


def test_loading_an_unknown_skill_names_the_real_ones() -> None:
    planner = make_planner()

    result = planner._execute_tool(
        FakeToolUse("load_skill", {"name": "sudo"}), StubStreamManager(), empty_usage(), [],
    )

    assert result.startswith("Error: Unknown skill")
    assert "diagnose" in result
