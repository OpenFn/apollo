"""Live checks on how the planner uses web_search and web_fetch.

These hit the live Anthropic API. Each test plays its scenario
once with the shipped prompt and config and asserts on the recorded
tool-call trace. A failure prints the full trace, no retries.
"""

import os
from dataclasses import dataclass

import pytest
from dotenv import load_dotenv

load_dotenv()

from global_chat.config_loader import ConfigLoader  # noqa: E402
from global_chat.planner import PlannerAgent  # noqa: E402
from global_chat.tests.web_tools.trace import build_trace, count, format_trace, is_grounded  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(bool(os.getenv("ANTHROPIC_BASE_URL")), reason="web tools need a direct api.anthropic.com key"),
    pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"),
]


@dataclass(frozen=True)
class Scenario:
    turns: tuple[str, ...]
    workflow_yaml: str | None = None
    page: str | None = None
    # Each fact must be in the answer and in a fetched page.
    facts: tuple[str, ...] = ()


FHIR_MAPPING_YAML = """\
name: commcare-to-fhir
jobs:
  map-patient:
    id: job-map-patient
    name: Map Patient
    adaptor: "@openfn/language-common@latest"
    body: |
      fn(state => {
        const patient = {
          resourceType: 'Patient',
          firstName: state.data.first_name,
          lastName: state.data.last_name,
          gender: state.data.sex,
        };
        return { ...state, patient };
      });
triggers:
  webhook:
    id: trigger-webhook
    type: webhook
    enabled: true
edges:
  webhook->map-patient:
    id: edge-webhook-map
    source_trigger: webhook
    target_job: map-patient
    condition_type: always
    enabled: true
"""

# Each scenario has a trap: a reason the model might use the web wrongly.
SCENARIOS = {
    # docs.openfn.org is allowlisted, which tempts a fetch; search_documentation is the right tool.
    "control_openfn_concept": Scenario(
        turns=("What does each() do in OpenFn job code, and when should I use it instead of fn()?",),
    ),
    # FHIR vocabulary is found everywhere, but this is a pure JavaScript edit.
    "control_code_edit": Scenario(
        turns=("In this step, rename the firstName field to given and wrap its value in an array.",),
        workflow_yaml=FHIR_MAPPING_YAML,
        page="workflows/commcare-to-fhir/map-patient",
    ),
    # Positive case: the pat-1 constraint sits near the end of what a 10k-token fetch of patient.html returns.
    "fhir_shallow": Scenario(
        turns=("In FHIR R4, what rule applies to each entry in Patient.contact? What must it contain at minimum?",),
        facts=("contact's details", "reference to an organization"),
    ),
    # The codes sit past where a 10k-token fetch of patient.html is cut off. They are also
    # near the top of the short valueset-link-type.html page, which the planner can read instead.
    "fhir_deep": Scenario(
        turns=("In FHIR R4, what codes can Patient.link.type take, and what does each mean?",),
        facts=("replaced-by", "seealso"),
    ),
    # The model knows docs.dhis2.org from training, but it is not on the allowlist.
    "off_allowlist": Scenario(
        turns=("What fields does the DHIS2 tracker API (/api/tracker) accept when creating an event?",),
    ),
    # Turn 2 is answerable from turn 1's page, and turn 3 barely needs it.
    "multi_turn": Scenario(
        turns=(
            "Which fields does a FHIR R4 Patient have for contact information?",
            "Which of those fields can repeat?",
            "How would I map a CommCare phone number into it?",
        ),
    ),
}


@pytest.mark.parametrize("scenario_id", ["control_openfn_concept", "control_code_edit"])
def test_controls_make_no_web_calls(scenario_id: str) -> None:
    turns = play(scenario_id)
    calls = all_calls(turns)

    assert count(calls, tool="search") + count(calls, tool="fetch") == 0, explain(turns)


MAX_FIRST_TURN_REFUSALS = 2


@pytest.mark.parametrize("scenario_id", ["fhir_shallow", "fhir_deep"])
def test_fhir_answers_come_from_a_fetched_page(scenario_id: str) -> None:
    turns = play(scenario_id)
    calls = all_calls(turns)

    assert count(calls, result="url_not_in_prior_context") <= MAX_FIRST_TURN_REFUSALS, explain(turns)
    assert count(calls, tool="fetch", result="ok") >= 1, explain(turns)
    assert is_grounded(turns[-1].answer, calls, SCENARIOS[scenario_id].facts), explain(turns)


def test_an_off_allowlist_question_does_not_try_banned_urls() -> None:
    turns = play("off_allowlist")
    calls = all_calls(turns)

    assert count(calls, result="url_not_allowed") == 0, explain(turns)
    assert count(calls, result="url_not_in_prior_context") == 0, explain(turns)


def test_follow_up_turns_do_not_fetch_the_same_content_again() -> None:
    turns = play("multi_turn")

    assert sum(count(turn.trace, tool="fetch") for turn in turns[1:]) <= 1, explain(turns)
    assert count(turns[0].trace, result="url_not_in_prior_context") <= MAX_FIRST_TURN_REFUSALS, explain(turns)
    assert sum(count(turn.trace, result="url_not_in_prior_context") for turn in turns[1:]) == 0, explain(turns)


@dataclass
class Turn:
    answer: str
    trace: list[dict]


class RecordingPlanner(PlannerAgent):
    """PlannerAgent with web search on, keeping each raw API response."""

    def __init__(self, config_loader: ConfigLoader) -> None:
        super().__init__(config_loader, web_search=True)
        self.responses: list = []

    def _call_api(self, *args: object, **kwargs: object) -> object:
        response = super()._call_api(*args, **kwargs)
        self.responses.append(response)
        return response


def play(scenario_id: str) -> list[Turn]:
    """Play every turn of a scenario live, carrying history the way return_history does."""
    scenario = SCENARIOS[scenario_id]
    config_loader = ConfigLoader()
    history: list[dict] = []
    turns: list[Turn] = []

    for content in scenario.turns:
        planner = RecordingPlanner(config_loader)
        result = planner.run(content, scenario.workflow_yaml, scenario.page, history, stream=False)
        assert not result.meta.get("web_search_downgraded"), "web tools were downgraded, so this key cannot use web search"
        turns.append(Turn(answer=result.response, trace=build_trace(planner.responses)))
        history = result.history

    return turns


def all_calls(turns: list[Turn]) -> list[dict]:
    return [call for turn in turns for call in turn.trace]


def explain(turns: list[Turn]) -> str:
    return "\n\n".join(
        f"turn {number}:\n{format_trace(turn.trace)}\n\nanswer:\n{turn.answer[:1500]}"
        for number, turn in enumerate(turns, start=1)
    )
