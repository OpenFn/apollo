"""Unit tests for `assert_no_special_chars`.

The assertion is what the live acceptance suites lean on to catch the
sanitizer misbehaving, so it needs to fail on the things the sanitizer can get
wrong — not just on a job name with an `@` in it.
"""

from pathlib import Path

import pytest
from name_rules import MAX_NAME_LENGTH, UNICODE_FLAG_ENV, describe_rule_for_judge
from testing import judges
from testing.judges import load_judge
from testing.yaml_assertions import assert_no_special_chars


@pytest.fixture
def ascii_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, "false")


@pytest.fixture
def unicode_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, "true")


def _workflow(**overrides: object) -> dict:
    data = {
        "jobs": {"fetch": {"name": "Fetch"}, "send": {"name": "Send"}},
        "triggers": {"webhook": {"type": "webhook"}},
        "edges": {
            "webhook->fetch": {"source_trigger": "webhook", "target_job": "fetch"},
            "fetch->send": {"source_job": "fetch", "target_job": "send"},
        },
    }
    data.update(overrides)
    return data


@pytest.mark.usefixtures("ascii_mode")
def test_accepts_a_clean_workflow() -> None:
    assert_no_special_chars(_workflow())


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_a_bad_job_name() -> None:
    workflow = _workflow(jobs={"fetch": {"name": "Vérifier l'état"}})
    workflow["edges"] = {}

    with pytest.raises(AssertionError, match="Job 'fetch' name"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_a_bad_job_key() -> None:
    """Job keys were never checked, which is how the key/name asymmetry hid."""
    workflow = _workflow(jobs={"患者確認": {"name": "Check"}}, edges={})

    with pytest.raises(AssertionError, match="Job key"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_a_bad_trigger_key() -> None:
    """Triggers were not checked at all, which is how the unsanitized ones sailed past."""
    workflow = _workflow(triggers={"ウェブ": {"type": "webhook"}}, edges={})

    with pytest.raises(AssertionError, match="Trigger key"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_a_name_over_the_length_cap() -> None:
    """Uses is_valid_name, so the cap is checked; a character-set regex missed this."""
    workflow = _workflow(jobs={"fetch": {"name": "x" * (MAX_NAME_LENGTH + 1)}}, edges={})

    with pytest.raises(AssertionError, match="does not obey the step-name rule"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_an_edge_whose_key_contradicts_its_endpoints() -> None:
    workflow = _workflow(
        edges={"fetch->nowhere": {"source_job": "fetch", "target_job": "send"}},
    )

    with pytest.raises(AssertionError, match="does not match its own endpoints"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_accepts_the_collision_suffix_the_sanitizer_adds() -> None:
    """Two edges between the same pair are legitimate, and the second gets a -N."""
    workflow = _workflow(
        edges={
            "fetch->send": {"source_job": "fetch", "target_job": "send"},
            "fetch->send-2": {"source_job": "fetch", "target_job": "send"},
        },
    )

    assert_no_special_chars(workflow)


@pytest.mark.usefixtures("unicode_mode")
def test_does_not_split_an_edge_key_on_an_arrow_inside_a_name() -> None:
    """Splitting on the first "->" is exactly the ambiguity the sanitizer avoids."""
    workflow = {
        "jobs": {"a->b": {"name": "a->b"}, "c": {"name": "C"}},
        "edges": {"a->b->c": {"source_job": "a->b", "target_job": "c"}},
    }

    assert_no_special_chars(workflow)


@pytest.mark.usefixtures("unicode_mode")
def test_permissive_mode_accepts_what_lightning_accepts() -> None:
    workflow = {
        "jobs": {
            "Vérifier l'état": {"name": "Vérifier l'état"},
            "患者確認": {"name": "患者確認 ✅"},
        },
        "edges": {
            "Vérifier l'état->患者確認": {
                "source_job": "Vérifier l'état",
                "target_job": "患者確認",
            },
        },
    }

    assert_no_special_chars(workflow)


@pytest.mark.usefixtures("unicode_mode")
def test_permissive_mode_still_rejects_a_control_character() -> None:
    workflow = _workflow(jobs={"fetch": {"name": "Fetch\x00Data"}}, edges={})

    with pytest.raises(AssertionError, match="does not obey the step-name rule"):
        assert_no_special_chars(workflow)


# --- the judges are generated from the same rule ------------------------------


def test_judges_state_the_active_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rubrics used to restate the rule as static prose, a third copy.

    With the ASCII rule active a hardcoded permissive rubric would pass a name
    the sanitizer is in fact folding, so the judge could no longer catch Apollo
    misbehaving.
    """
    monkeypatch.setenv(UNICODE_FLAG_ENV, "false")
    ascii_rules = load_judge("general").rules
    assert describe_rule_for_judge() in ascii_rules
    assert "unaccented English letters" in ascii_rules

    monkeypatch.setenv(UNICODE_FLAG_ENV, "true")
    unicode_rules = load_judge("general").rules
    assert describe_rule_for_judge() in unicode_rules
    assert "no control characters" in unicode_rules

    assert ascii_rules != unicode_rules


#: Every judge on disk, not a hardcoded pair — a new rubric that restates the
#: rule by hand would otherwise never be checked.
ALL_JUDGES = sorted(p.stem for p in (Path(judges.__file__).parent / "judges").glob("*.md"))


def test_the_judge_list_is_not_empty() -> None:
    """Guards the glob: an empty list would make every test below vacuous."""
    assert ALL_JUDGES


@pytest.mark.parametrize("judge", ALL_JUDGES)
def test_no_judge_leaves_the_placeholder_unsubstituted(judge: str) -> None:
    config = load_judge(judge)
    assert "{name_rule}" not in config.rules
    assert "{name_rule}" not in config.role


@pytest.mark.parametrize("judge", ALL_JUDGES)
def test_a_judge_that_uses_the_token_gets_the_active_rule(judge: str) -> None:
    """Not every judge needs it — the code-quality one grades job bodies, not names."""
    raw = (Path(judges.__file__).parent / "judges" / f"{judge}.md").read_text()
    if "{name_rule}" not in raw:
        pytest.skip(f"{judge} does not grade names")

    assert describe_rule_for_judge() in load_judge(judge).rules


@pytest.mark.parametrize("judge", ALL_JUDGES)
def test_no_judge_hardcodes_a_naming_rule(judge: str) -> None:
    """A hand-written charset is the drift this whole indirection exists to stop."""
    raw = (Path(judges.__file__).parent / "judges" / f"{judge}.md").read_text().lower()

    for phrase in (
        "letters, numbers, spaces",
        "letters, digits, spaces",
        "hyphens, and underscores",
        "no special characters",
    ):
        assert phrase not in raw, f"{judge} states the naming rule itself; use {{name_rule}}"


def test_a_mangled_placeholder_is_rejected_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`str.replace` is a silent no-op on a misspelled token, so it must raise."""
    monkeypatch.setattr(judges, "_JUDGES_DIR", tmp_path)
    (tmp_path / "typo.md").write_text("# role\nA judge\n\n# rules\n- {name_rules}\n")

    with pytest.raises(ValueError, match="unsubstituted placeholders"):
        load_judge("typo")


def test_prose_braces_are_not_mistaken_for_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The code-quality judge is full of JS snippets; none of them may trip it."""
    monkeypatch.setattr(judges, "_JUDGES_DIR", tmp_path)
    (tmp_path / "code.md").write_text(
        "# role\nA judge\n\n# rules\n- `create({ name: $.patient.name })` and `() => {}`\n",
    )

    assert load_judge("code").rules


# --- null sections ------------------------------------------------------------


@pytest.mark.parametrize(
    "workflow",
    [
        {"jobs": None},
        {"edges": None},
        {"triggers": None},
        {"jobs": None, "edges": None, "triggers": None},
        {},
    ],
)
def test_tolerates_an_empty_section(workflow: dict) -> None:
    """`edges:` with nothing under it is valid YAML and parses as None."""
    assert_no_special_chars(workflow)


# --- referential integrity ----------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_an_edge_pointing_at_a_job_that_does_not_exist() -> None:
    """A well-formed name that names nothing is what a broken mapping produces."""
    workflow = _workflow(edges={"fetch->ghost": {"source_job": "fetch", "target_job": "ghost"}})

    with pytest.raises(AssertionError, match="is not a job in this workflow"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_a_trigger_reference_that_names_a_job() -> None:
    """The exact shape a shared job/trigger key mapping produced."""
    workflow = _workflow(
        edges={"fetch->send": {"source_trigger": "fetch", "target_job": "send"}},
    )

    with pytest.raises(AssertionError, match="is not a trigger in this workflow"):
        assert_no_special_chars(workflow)


@pytest.mark.usefixtures("ascii_mode")
def test_rejects_an_over_long_edge_key() -> None:
    long_name = "a" * MAX_NAME_LENGTH
    workflow = {
        "jobs": {long_name: {"name": "A"}, "b": {"name": "B"}},
        "edges": {f"{long_name}->{long_name}->b": {"source_job": long_name, "target_job": "b"}},
    }

    with pytest.raises(AssertionError):
        assert_no_special_chars(workflow)
