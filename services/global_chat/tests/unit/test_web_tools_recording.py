"""Unit tests for the web-tools recording planner, variants and config overrides."""

import pytest
from global_chat.config_loader import ConfigLoader
from global_chat.tests.web_tools import recording
from global_chat.tests.web_tools.recording import OverrideConfigLoader, RecordingPlanner, fingerprint
from global_chat.tests.web_tools.variants import (
    ENTRY_URLS,
    EXAMPLE_URL,
    FINDINGS,
    SEARCH_FIRST,
    STAGES,
    resolve_variant,
)


def test_base_is_the_shipped_config() -> None:
    variant = resolve_variant("base")

    assert (variant.web_search, variant.prompt_suffix, variant.inject_urls) == ({}, "", ())


def test_variants_compose_left_to_right() -> None:
    variant = resolve_variant("base+1c+findings+25k")

    assert variant.name == "base+1c+findings+25k"
    assert SEARCH_FIRST in variant.prompt_suffix
    assert FINDINGS in variant.prompt_suffix
    assert variant.inject_urls == ENTRY_URLS
    assert variant.web_search == {"max_content_tokens": 25000}
    assert variant.complexity == len(["prompt", "code"])


def test_an_unknown_variant_part_is_an_error() -> None:
    with pytest.raises(KeyError):
        resolve_variant("base+nope")


def test_every_stage_names_real_variants() -> None:
    for stage in STAGES.values():
        for name in stage["variants"]:
            resolve_variant(f"base+{name}")


OVERRIDE_TOKENS = 40000


def test_override_loader_applies_the_variant_without_touching_the_files() -> None:
    loader = OverrideConfigLoader(resolve_variant("base+findings+40k"))
    fresh = ConfigLoader()

    assert loader.config["planner"]["web_search"]["max_content_tokens"] == OVERRIDE_TOKENS
    assert loader.get_prompt("planner_web_tools_prompt").rstrip().endswith(FINDINGS)
    assert fresh.config["planner"]["web_search"]["max_content_tokens"] != OVERRIDE_TOKENS
    assert FINDINGS not in fresh.get_prompt("planner_web_tools_prompt")


def test_a_suffix_already_in_the_prompt_is_not_added_twice() -> None:
    prompts = {"planner_web_tools_prompt": f"intro\n{SEARCH_FIRST}\n"}

    recording.apply_prompt_changes(prompts, resolve_variant("base+1a"))

    assert prompts["planner_web_tools_prompt"].count(SEARCH_FIRST) == 1


def test_1d_drops_the_example_url_and_adds_the_search_first_line() -> None:
    shipped = ConfigLoader().get_prompt("planner_web_tools_prompt")
    prompt = OverrideConfigLoader(resolve_variant("base+1d")).get_prompt("planner_web_tools_prompt")

    assert EXAMPLE_URL in shipped
    assert EXAMPLE_URL not in prompt
    assert "https://hl7.org/fhir/R4/patient.html" not in prompt
    assert "`https://hl7.org/fhir/R4/`" in prompt
    assert prompt.rstrip().endswith(SEARCH_FIRST)


def test_a_removal_that_matches_nothing_is_an_error() -> None:
    prompts = {"planner_web_tools_prompt": "no example here"}

    with pytest.raises(ValueError, match="not in"):
        recording.apply_prompt_changes(prompts, resolve_variant("base+1d"))


def make_recording_planner(inject_urls: tuple[str, ...]) -> RecordingPlanner:
    planner = RecordingPlanner.__new__(RecordingPlanner)
    planner.inject_urls = inject_urls
    planner._attachments = []
    planner.current_yaml = None
    return planner


def test_injected_urls_are_appended_to_the_user_turn() -> None:
    content = make_recording_planner(ENTRY_URLS)._build_user_content("What is Patient.gender?", None)

    assert content.startswith("What is Patient.gender?")
    for url in ENTRY_URLS:
        assert url in content


def test_nothing_is_appended_without_injected_urls() -> None:
    assert make_recording_planner(())._build_user_content("q", None) == "q"


def test_the_fingerprint_changes_with_anything_that_changes_behaviour() -> None:
    prints = {fingerprint(resolve_variant(name)) for name in ("base", "base+findings", "base+1b", "base+25k")}

    assert len(prints) == len(["base", "base+findings", "base+1b", "base+25k"])
    assert fingerprint(resolve_variant("base")) == fingerprint(resolve_variant("base"))


class Scenario:
    turns = ("first", "second")
    workflow_yaml = None
    page = None


class FailingPlanner:
    """Stands in for RecordingPlanner: one recorded round, then the API fails."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.responses = []

    def run(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("overloaded")


def test_a_failed_turn_is_recorded_and_ends_the_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recording, "RecordingPlanner", FailingPlanner)

    turns = recording.run_scenario(Scenario(), resolve_variant("base"))

    assert len(turns) == 1
    assert turns[0].error == "RuntimeError: overloaded"
    assert turns[0].answer == ""


def test_the_shipped_prompt_is_the_measured_1a_prompt() -> None:
    assert fingerprint(resolve_variant("base")) == fingerprint(resolve_variant("base+1a"))


def test_a_shipped_suffix_is_not_repeated_when_composed_with_another() -> None:
    prompt = OverrideConfigLoader(resolve_variant("base+1a+findings")).get_prompt("planner_web_tools_prompt")

    assert prompt.count(SEARCH_FIRST) == 1
    assert FINDINGS in prompt


def test_the_fingerprint_covers_the_resolved_model_and_the_whole_planner_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = fingerprint(resolve_variant("base"))

    monkeypatch.setitem(recording.CLAUDE_MODELS, "claude-opus", "claude-opus-next")
    after_model = fingerprint(resolve_variant("base"))
    monkeypatch.undo()

    original_init = OverrideConfigLoader.__init__

    def init_with_more_tool_calls(self: OverrideConfigLoader, variant: object) -> None:
        original_init(self, variant)
        self.config["planner"]["max_tool_calls"] = 99

    monkeypatch.setattr(OverrideConfigLoader, "__init__", init_with_more_tool_calls)
    after_config = fingerprint(resolve_variant("base"))

    assert before != after_model
    assert before != after_config


def test_the_scenario_key_changes_when_the_scenario_content_changes() -> None:
    class Edited:
        turns = ("a different question",)
        workflow_yaml = None
        page = None

    assert recording.scenario_key(Scenario()) != recording.scenario_key(Edited())
    assert recording.scenario_key(Scenario()) == recording.scenario_key(Scenario())


class UnbuildablePlanner:
    """Stands in for RecordingPlanner when PlannerAgent itself refuses to build."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("ANTHROPIC_API_KEY not found")


def test_a_planner_that_cannot_be_built_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recording, "RecordingPlanner", UnbuildablePlanner)

    turns = recording.run_scenario(Scenario(), resolve_variant("base"))

    assert len(turns) == 1
    assert turns[0].error == "RuntimeError: ANTHROPIC_API_KEY not found"
