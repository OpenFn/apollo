"""Unit tests that the web-tools scenarios are well formed."""

from global_chat.tests.web_tools.scenarios import SCENARIOS
from global_chat.tests.web_tools.variants import STAGES


def test_every_stage_names_real_scenarios() -> None:
    for stage in STAGES.values():
        for scenario_id in stage["scenarios"]:
            assert scenario_id in SCENARIOS


def test_ids_match_their_keys() -> None:
    assert all(key == scenario.id for key, scenario in SCENARIOS.items())


def test_controls_have_no_facts_and_fhir_scenarios_do() -> None:
    for scenario in SCENARIOS.values():
        if scenario.control:
            assert scenario.facts == ()
    assert SCENARIOS["fhir_shallow"].facts
    assert SCENARIOS["fhir_deep"].facts


def test_multi_turn_has_several_turns() -> None:
    assert len(SCENARIOS["multi_turn"].turns) > 1
    assert all(len(s.turns) == 1 for k, s in SCENARIOS.items() if k != "multi_turn")


def test_the_code_edit_control_points_at_a_real_step() -> None:
    scenario = SCENARIOS["control_code_edit"]
    assert scenario.page is not None
    assert scenario.workflow_yaml is not None

    assert scenario.page.rsplit("/", 1)[-1] in scenario.workflow_yaml
