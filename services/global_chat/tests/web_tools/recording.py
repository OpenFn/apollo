"""Run the planner in-process and keep every raw API response it received."""

import hashlib
import json
import time
from typing import Protocol

from global_chat.config_loader import ConfigLoader
from global_chat.planner import PlannerAgent

from .metrics import TurnRecord
from .trace import build_trace
from .variants import INJECT_TEMPLATE, Variant

WEB_PROMPT_KEY = "planner_web_tools_prompt"
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class PlayableScenario(Protocol):
    """What run_scenario reads from a scenario; scenarios.Scenario satisfies it."""

    @property
    def turns(self) -> tuple[str, ...]: ...

    @property
    def workflow_yaml(self) -> str | None: ...

    @property
    def page(self) -> str | None: ...


class OverrideConfigLoader(ConfigLoader):
    """The shipped config and prompts with one variant applied in memory."""

    def __init__(self, variant: Variant) -> None:
        super().__init__()
        self.config["planner"]["web_search"].update(variant.web_search)
        apply_prompt_changes(self.prompts["prompts"], variant)


class RecordingPlanner(PlannerAgent):
    """PlannerAgent with web search on, recording each round's raw response."""

    def __init__(self, config_loader: ConfigLoader, inject_urls: tuple[str, ...] = (), api_key: str | None = None) -> None:
        super().__init__(config_loader, api_key=api_key, web_search=True)
        self.inject_urls = tuple(inject_urls)
        self.responses: list = []

    def _call_api(self, *args: object, **kwargs: object) -> object:
        response = super()._call_api(*args, **kwargs)
        self.responses.append(response)
        return response

    def _build_user_content(self, content: str, page: str | None) -> str:
        user_content = super()._build_user_content(content, page)
        if self.inject_urls:
            user_content += "\n\n" + INJECT_TEMPLATE.format(urls=", ".join(self.inject_urls))
        return user_content


def apply_prompt_changes(prompts: dict, variant: Variant) -> None:
    """Remove the variant's exact text from the web prompt, then append its suffix.

    A removal that matches nothing raises, so a prompts.yaml edit can never turn
    a variant silently into a different one.
    """
    text = prompts[WEB_PROMPT_KEY]
    for removal in variant.prompt_removals:
        if removal not in text:
            raise ValueError(f"{removal!r} not in {WEB_PROMPT_KEY}")
        text = text.replace(removal, "")
    if variant.prompt_suffix and variant.prompt_suffix not in text:
        text = text.rstrip("\n") + "\n" + variant.prompt_suffix + "\n"
    prompts[WEB_PROMPT_KEY] = text


def fingerprint(variant: Variant) -> str:
    """A short hash of everything that changes planner behaviour, used to key cached runs."""
    loader = OverrideConfigLoader(variant)
    material = {
        "model": loader.config["planner"].get("model"),
        "web_search": loader.config["planner"]["web_search"],
        "system": loader.get_prompt("planner_system_prompt"),
        "web_prompt": loader.get_prompt(WEB_PROMPT_KEY),
        "inject": list(variant.inject_urls),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:10]


def run_scenario(scenario: PlayableScenario, variant: Variant) -> list[TurnRecord]:
    """Play every turn of a scenario live, carrying history the way return_history does."""
    loader = OverrideConfigLoader(variant)
    history: list[dict] = []
    turns: list[TurnRecord] = []

    for content in scenario.turns:
        planner = RecordingPlanner(loader, inject_urls=variant.inject_urls)
        start = time.monotonic()
        try:
            result = planner.run(content, scenario.workflow_yaml, scenario.page, history, stream=False)
        except Exception as error:  # recorded as a failed run
            turns.append(TurnRecord(
                answer="",
                trace=build_trace(planner.responses),
                usage=usage(planner.responses),
                seconds=time.monotonic() - start,
                rounds=len(planner.responses),
                error=f"{type(error).__name__}: {error}",
            ))
            break

        turns.append(TurnRecord(
            answer=result.response,
            trace=build_trace(planner.responses),
            usage=usage(planner.responses),
            seconds=time.monotonic() - start,
            rounds=len(planner.responses),
            downgraded=bool(result.meta.get("web_search_downgraded")),
        ))
        history = result.history

    return turns


def usage(responses: list) -> dict:
    return {key: sum(getattr(r.usage, key, 0) or 0 for r in responses) for key in USAGE_FIELDS}
