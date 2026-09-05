"""Job-name sanitizing, in both step-name modes.

The rule is switchable at runtime (see `name_rules`), so every test here pins
the mode it is testing with the APOLLO_UNICODE_STEP_NAMES environment variable
rather than relying on whatever the environment happens to be set to.
"""

import unicodedata

import pytest
import yaml
from name_rules import (
    MAX_EDGE_KEY_LENGTH,
    MAX_NAME_LENGTH,
    UNICODE_FLAG_ENV,
    grapheme_length,
)
from testing.yaml_assertions import assert_no_special_chars
from workflow_chat.workflow_chat import AnthropicClient


@pytest.fixture
def ascii_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the restrictive ASCII rule (the default)."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, "false")


@pytest.fixture
def unicode_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the permissive Unicode rule."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, "true")


# --- default (ASCII) mode ---------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_default_mode_is_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag unset at all, the ASCII rule applies."""
    monkeypatch.delenv(UNICODE_FLAG_ENV, raising=False)
    yaml_data = {"jobs": {"job1": {"name": "Café München"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"


@pytest.mark.usefixtures("ascii_mode")
def test_ascii_mode_removes_diacritics() -> None:
    yaml_data = {
        "jobs": {
            "job1": {"name": "Café München"},
            "job2": {"name": "Naïve résumé"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"
    assert yaml_data["jobs"]["job2"]["name"] == "Naive resume"


@pytest.mark.usefixtures("ascii_mode")
def test_ascii_mode_removes_special_characters() -> None:
    yaml_data = {
        "jobs": {
            "job1": {"name": "Job@#$%Name!"},
            "job2": {"name": "Process&Data*With+Symbols"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "JobName"
    assert yaml_data["jobs"]["job2"]["name"] == "ProcessDataWithSymbols"


@pytest.mark.usefixtures("ascii_mode")
def test_ascii_mode_preserves_allowed_characters() -> None:
    yaml_data = {"jobs": {"job1": {"name": "Valid Job-Name_123"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Valid Job-Name_123"


def test_handles_empty_data() -> None:
    assert AnthropicClient.sanitize_job_names(None) is None
    assert AnthropicClient.sanitize_job_names({}) is None
    assert AnthropicClient.sanitize_job_names({"jobs": {}}) is None


@pytest.mark.parametrize("payload", [[], "not a workflow", 42, 0.5, {"jobs": "nope"}])
def test_tolerates_a_payload_that_is_not_a_workflow(payload: object) -> None:
    """One call site swallows every exception from this, so raising loses the YAML silently."""
    assert AnthropicClient.sanitize_job_names(payload) is None


# --- Unicode mode -----------------------------------------------------------


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_mode_keeps_accents_and_apostrophes() -> None:
    yaml_data = {
        "jobs": {
            "job1": {"name": "Vérifier l'état"},
            "job2": {"name": "O'Brien's Step"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Vérifier l'état"
    assert yaml_data["jobs"]["job2"]["name"] == "O'Brien's Step"


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_mode_keeps_non_latin_scripts() -> None:
    yaml_data = {
        "jobs": {
            "job1": {"name": "患者確認"},
            "job2": {"name": "Проверка данных"},
            "job3": {"name": "ß straße"},
            "job4": {"name": "रोगी की जाँच"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "患者確認"
    assert yaml_data["jobs"]["job2"]["name"] == "Проверка данных"
    assert yaml_data["jobs"]["job3"]["name"] == "ß straße"
    assert yaml_data["jobs"]["job4"]["name"] == "रोगी की जाँच"


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_mode_keeps_symbols_and_punctuation() -> None:
    """The permissive rule strips nothing but control characters."""
    yaml_data = {
        "jobs": {
            "job1": {"name": "Résumé ✅ @#$%"},
            "job2": {"name": "Import A/B"},
            "job3": {"name": "50% & rising"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Résumé ✅ @#$%"
    assert yaml_data["jobs"]["job2"]["name"] == "Import A/B"
    assert yaml_data["jobs"]["job3"]["name"] == "50% & rising"


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_mode_keeps_an_arrow_inside_a_name() -> None:
    """Nothing anywhere splits an edge key on "->" — it is a label, not identity.

    The edge label is rebuilt from `source_job`/`target_job`, so a name
    containing "->" cannot dangle an edge.
    """
    yaml_data = {
        "jobs": {"a->b": {"name": "a->b"}, "c": {"name": "C"}},
        "edges": {
            "a->b->c": {"source_job": "a->b", "target_job": "c"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["a->b"]["name"] == "a->b"
    assert list(yaml_data["jobs"]) == ["a->b", "c"]
    edge = yaml_data["edges"]["a->b->c"]
    assert edge["source_job"] == "a->b"
    assert edge["target_job"] == "c"


# --- control characters, rejected in every mode -----------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_control_characters_are_rejected_in_every_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """A NUL byte crashes Lightning's Postgres insert, so it never gets through."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {"jobs": {"job1": {"name": "Fetch\x00Data\x1b[31m\x9b"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    name = yaml_data["jobs"]["job1"]["name"]
    assert "\x00" not in name
    assert "\x1b" not in name
    assert "\x9b" not in name
    # Only the controls go. The "[" is an ordinary character, so it survives
    # under the permissive rule and is dropped by the ASCII whitelist.
    assert name == ("FetchData[31m" if mode == "true" else "FetchData31m")


@pytest.mark.parametrize("mode", ["false", "true"])
def test_noncharacters_are_rejected_in_every_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {"jobs": {"job1": {"name": "Fetch\ufffeData\uffff"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "FetchData"


@pytest.mark.parametrize("mode", ["false", "true"])
def test_tabs_and_newlines_become_spaces(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {"jobs": {"job1": {"name": "Fetch\tthe\ndata"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Fetch the data"


@pytest.mark.parametrize("mode", ["false", "true"])
def test_names_are_trimmed_and_capped(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {"jobs": {"job1": {"name": "  Fetch Data  "}, "job2": {"name": "a" * 200}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Fetch Data"
    assert len(yaml_data["jobs"]["job2"]["name"]) == MAX_NAME_LENGTH


# --- collisions -------------------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_names_that_sanitize_to_the_same_string_stay_distinct() -> None:
    """`Résumé` and `Resume` both fold to `Resume` under the ASCII rule.

    The prompt requires job names to be unique within a workflow, and Lightning
    enforces it with a unique index, so the second one has to be nudged.
    """
    yaml_data = {"jobs": {"a": {"name": "Résumé"}, "b": {"name": "Resume"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    names = [job["name"] for job in yaml_data["jobs"].values()]
    assert names == ["Resume", "Resume-2"]
    assert len(set(names)) == len(names)


@pytest.mark.usefixtures("ascii_mode")
def test_job_keys_that_sanitize_to_the_same_string_stay_distinct() -> None:
    yaml_data = {
        "jobs": {"résumé": {"name": "One"}, "resume": {"name": "Two"}},
        "edges": {
            "résumé->resume": {"source_job": "résumé", "target_job": "resume"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["jobs"]) == ["resume", "resume-2"]
    edge = yaml_data["edges"]["resume->resume-2"]
    assert edge["source_job"] == "resume"
    assert edge["target_job"] == "resume-2"


@pytest.mark.usefixtures("ascii_mode")
def test_name_that_sanitizes_away_falls_back_to_the_job_key() -> None:
    """A wholly non-Latin name folds to nothing under the ASCII rule.

    An empty name fails Lightning's `validate_required`, so fall back to
    something rather than emitting a workflow that cannot be saved.
    """
    yaml_data = {"jobs": {"check-patient": {"name": "患者確認"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["check-patient"]["name"] == "check-patient"


@pytest.mark.usefixtures("ascii_mode")
def test_key_that_sanitizes_away_falls_back_to_a_positional_key() -> None:
    yaml_data = {"jobs": {"患者確認": {"name": "Check Patient"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["jobs"]) == ["step-1"]
    assert yaml_data["jobs"]["step-1"]["name"] == "Check Patient"


# --- the jobs-key / edge-reference asymmetry --------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_job_keys_and_edge_references_stay_in_step() -> None:
    """Edges must still point at jobs that exist after sanitizing.

    Job keys used to be left alone while edge references were sanitized, so a
    workflow keyed on a non-ASCII name came out with every edge dangling.
    """
    yaml_data = {
        "jobs": {
            "Vérifier-l-état": {"name": "Vérifier l'état"},
            "envoyer-données": {"name": "Envoyer données"},
        },
        "triggers": {"webhook": {"type": "webhook"}},
        "edges": {
            "webhook->Vérifier-l-état": {
                "source_trigger": "webhook",
                "target_job": "Vérifier-l-état",
            },
            "Vérifier-l-état->envoyer-données": {
                "source_job": "Vérifier-l-état",
                "target_job": "envoyer-données",
            },
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    job_keys = set(yaml_data["jobs"])
    assert job_keys == {"Verifier-l-etat", "envoyer-donnees"}

    for edge_key, edge in yaml_data["edges"].items():
        source, target = edge_key.split("->", 1)
        assert target in job_keys, f"edge key '{edge_key}' targets a job that does not exist"
        if source != "webhook":
            assert source in job_keys, f"edge key '{edge_key}' sources a job that does not exist"
        for field in ("source_job", "target_job"):
            if field in edge:
                assert edge[field] in job_keys, f"edge {field} '{edge[field]}' is not a job"


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_mode_leaves_a_valid_workflow_untouched() -> None:
    yaml_data = {
        "jobs": {
            "Vérifier-l-état": {"name": "Vérifier l'état"},
            "患者確認": {"name": "患者確認"},
        },
        "edges": {
            "Vérifier-l-état->患者確認": {
                "source_job": "Vérifier-l-état",
                "target_job": "患者確認",
            },
        },
    }
    before = yaml_data.copy()

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["jobs"]) == ["Vérifier-l-état", "患者確認"]
    assert yaml_data["edges"] == before["edges"]


@pytest.mark.usefixtures("ascii_mode")
def test_an_edge_with_no_usable_endpoints_keeps_its_key() -> None:
    """Only when there is nothing to derive a label from.

    An edge that *does* have endpoints gets the derived label even if its key
    has no arrow — see test_an_edge_key_with_no_arrow_still_gets_the_derived_label.
    """
    yaml_data = {
        "jobs": {"a": {"name": "A"}},
        "edges": {"some-edge": {"condition_type": "always"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["edges"]) == ["some-edge"]


# --- two edges between the same pair ------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_two_edges_between_the_same_pair_both_survive() -> None:
    """An on_success and an on_failure edge between two steps is an ordinary workflow.

    The label is derived from the endpoints, which is not injective, so keying
    on the bare label would silently drop one of the two edges.
    """
    yaml_data = {
        "jobs": {"A": {"name": "A"}, "B": {"name": "B"}},
        "edges": {
            "A->B": {"source_job": "A", "target_job": "B", "condition_type": "on_job_success"},
            "A->B (on failure)": {
                "source_job": "A", "target_job": "B", "condition_type": "on_job_failure",
            },
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    conditions = sorted(edge["condition_type"] for edge in yaml_data["edges"].values())
    assert conditions == ["on_job_failure", "on_job_success"]
    for edge in yaml_data["edges"].values():
        assert edge["source_job"] == "A"
        assert edge["target_job"] == "B"


@pytest.mark.usefixtures("ascii_mode")
def test_three_edges_between_the_same_pair_all_survive() -> None:
    yaml_data = {
        "jobs": {"A": {"name": "A"}, "B": {"name": "B"}},
        "edges": {
            f"A->B ({n})": {"source_job": "A", "target_job": "B", "n": n}
            for n in range(3)
        },
    }

    expected = sorted(edge["n"] for edge in yaml_data["edges"].values())

    AnthropicClient.sanitize_job_names(yaml_data)

    assert sorted(edge["n"] for edge in yaml_data["edges"].values()) == expected


# --- the uniquifying suffix must live inside the cap --------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_uniquifying_suffix_does_not_push_a_name_over_the_cap(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {
        "jobs": {
            "a": {"name": "x" * MAX_NAME_LENGTH},
            "b": {"name": "x" * MAX_NAME_LENGTH},
            "c": {"name": "x" * MAX_NAME_LENGTH},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    names = [job["name"] for job in yaml_data["jobs"].values()]
    assert len(set(names)) == len(names), "names collapsed onto each other"
    for name in names:
        assert grapheme_length(name) <= MAX_NAME_LENGTH


@pytest.mark.parametrize("mode", ["false", "true"])
def test_uniquifying_long_job_keys_stays_inside_the_cap(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    long_key = "k" * MAX_NAME_LENGTH
    yaml_data = {"jobs": {long_key: {"name": "A"}, long_key + "!": {"name": "B"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    keys = list(yaml_data["jobs"])
    assert len(set(keys)) == len(keys)
    for key in keys:
        assert grapheme_length(key) <= MAX_NAME_LENGTH


# --- references that sanitize away -------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_a_reference_that_sanitizes_away_does_not_leak_the_raw_value() -> None:
    """Returning the original on an empty result put raw non-ASCII back into the YAML."""
    yaml_data = {
        "jobs": {"a": {"name": "A"}},
        "edges": {"患者->a": {"source_job": "患者", "target_job": "a"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] == AnthropicClient.UNRESOLVED_REFERENCE
    assert "患者" not in str(yaml_data)


# --- triggers -----------------------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_trigger_keys_and_references_are_sanitized_too() -> None:
    """Triggers were read for the edge label but never sanitized or remapped."""
    yaml_data = {
        "jobs": {"a": {"name": "A"}},
        "triggers": {"ウェブフック": {"type": "webhook"}},
        "edges": {"ウェブフック->a": {"source_trigger": "ウェブフック", "target_job": "a"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    trigger_key = next(iter(yaml_data["triggers"]))
    assert trigger_key.isascii()
    edge_key, edge = next(iter(yaml_data["edges"].items()))
    assert edge["source_trigger"] == trigger_key
    assert edge_key == f"{trigger_key}->a"
    assert "ウェブフック" not in str(yaml_data)


@pytest.mark.usefixtures("unicode_mode")
def test_permissive_mode_leaves_a_non_latin_trigger_alone() -> None:
    yaml_data = {
        "jobs": {"a": {"name": "A"}},
        "triggers": {"ウェブフック": {"type": "webhook"}},
        "edges": {"ウェブフック->a": {"source_trigger": "ウェブフック", "target_job": "a"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["triggers"]) == ["ウェブフック"]
    assert list(yaml_data["edges"]) == ["ウェブフック->a"]


# --- jobs and triggers must not share a namespace -----------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_a_trigger_and_a_job_with_the_same_original_key_stay_separate() -> None:
    """One shared mapping let the jobs pass overwrite the trigger's entry.

    The edge's source_trigger then pointed at a job and the trigger was
    orphaned, which reads as a valid workflow and is not one.
    """
    yaml_data = {
        "triggers": {"Café": {"type": "webhook"}},
        "jobs": {"Cafe": {"name": "One"}, "Café": {"name": "Two"}},
        "edges": {"Café->Cafe": {"source_trigger": "Café", "target_job": "Cafe"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    trigger_key = next(iter(yaml_data["triggers"]))
    edge = next(iter(yaml_data["edges"].values()))

    assert edge["source_trigger"] == trigger_key, "trigger reference was bound to a job"
    assert edge["source_trigger"] not in yaml_data["jobs"] or trigger_key in yaml_data["jobs"]
    assert edge["target_job"] in yaml_data["jobs"]


@pytest.mark.usefixtures("unicode_mode")
def test_trailing_whitespace_cannot_collide_a_trigger_onto_a_job() -> None:
    """Permissive mode reaches the same collision through trimming."""
    yaml_data = {
        "triggers": {"hook ": {"type": "webhook"}},
        "jobs": {"hook": {"name": "A"}, "hook  ": {"name": "B"}},
        "edges": {"hook ->hook": {"source_trigger": "hook ", "target_job": "hook"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_trigger"] in yaml_data["triggers"]
    assert edge["target_job"] in yaml_data["jobs"]


# --- the unresolved sentinel --------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_the_sentinel_cannot_bind_to_a_real_step_of_the_same_name() -> None:
    """A user may name a step `unresolved-step`; keys are uniquified against
    each other, not against the sentinel."""
    yaml_data = {
        "jobs": {AnthropicClient.UNRESOLVED_REFERENCE: {"name": "Real Step"}},
        "edges": {
            "患者->x": {
                "source_job": "患者",
                "target_job": AnthropicClient.UNRESOLVED_REFERENCE,
            },
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["target_job"] == AnthropicClient.UNRESOLVED_REFERENCE
    assert edge["source_job"] not in yaml_data["jobs"], "sentinel bound to a real step"


# --- the sanitiser and its assertion must agree -------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_an_edge_key_with_no_arrow_still_gets_the_derived_label() -> None:
    """Leaving it alone here while the test assertion demanded the label meant
    the sanitiser emitted output its own assertion rejected."""
    yaml_data = {
        "jobs": {"A": {"name": "A"}, "B": {"name": "B"}},
        "edges": {"e1": {"source_job": "A", "target_job": "B"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["edges"]) == ["A->B"]
    assert_no_special_chars(yaml_data, context="derived label")


@pytest.mark.parametrize("mode", ["false", "true"])
def test_sanitised_output_always_satisfies_its_own_assertion(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {
        "triggers": {"webhook": {"type": "webhook"}},
        "jobs": {
            "Vérifier-l-état": {"name": "Vérifier l'état"},
            "患者確認": {"name": "患者確認"},
            "x" * 120: {"name": "y" * 120},
        },
        "edges": {
            "webhook->Vérifier-l-état": {
                "source_trigger": "webhook", "target_job": "Vérifier-l-état",
            },
            "e-no-arrow": {"source_job": "Vérifier-l-état", "target_job": "患者確認"},
            "long": {"source_job": "x" * 120, "target_job": "患者確認"},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert_no_special_chars(yaml_data, context=f"mode={mode}")


# --- edge key length ----------------------------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_edge_keys_are_length_capped(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    first, second = "a" * MAX_NAME_LENGTH, "b" * MAX_NAME_LENGTH
    yaml_data = {
        "jobs": {first: {"name": "A"}, second: {"name": "B"}},
        "edges": {"k": {"source_job": first, "target_job": second}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    for edge_key in yaml_data["edges"]:
        assert grapheme_length(edge_key) <= MAX_EDGE_KEY_LENGTH


# --- null sections across the whole finalize pipeline -------------------------

NULL_SECTION_DOCUMENTS = [
    "name: w\njobs:\n  a:\n    id: x\n    body: code()\n  b:\nedges:\n",
    "name: w\njobs:\nedges:\n",
    "name: w\ntriggers:\n  webhook:\nedges:\n  e:\n",
    "name: w\njobs:\n  a:\nedges:\n  a->a:\n",
    "name: w\n",
]




# --- referential integrity at runtime -----------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_an_edge_referring_to_a_step_by_name_is_resolved_to_its_key() -> None:
    """The likeliest real model mistake. It used to ship as a well-formed
    dangling edge with nothing logged."""
    yaml_data = {
        "jobs": {"fetch-data": {"name": "Fetch Data"}, "send": {"name": "Send"}},
        "edges": {"e": {"source_job": "Fetch Data", "target_job": "send"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] == "fetch-data"
    assert_no_special_chars(yaml_data, context="by-name reference")


@pytest.mark.usefixtures("ascii_mode")
def test_a_genuinely_dangling_edge_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    yaml_data = {
        "jobs": {"a": {"name": "A"}},
        "edges": {"e": {"source_job": "nowhere-at-all", "target_job": "a"}},
    }

    with caplog.at_level("WARNING"):
        AnthropicClient.sanitize_job_names(yaml_data)

    assert any("match no step or trigger" in r.message for r in caplog.records)


@pytest.mark.usefixtures("ascii_mode")
def test_the_sentinel_is_unique_against_job_names_too() -> None:
    yaml_data = {
        "jobs": {"a": {"name": AnthropicClient.UNRESOLVED_REFERENCE}},
        "edges": {"e": {"source_job": "患者", "target_job": "a"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    names = {job["name"] for job in yaml_data["jobs"].values()}
    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] not in names


# --- typed keys ---------------------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_an_int_key_and_a_string_key_do_not_shadow_each_other() -> None:
    """YAML gives `1:` as the int 1 and `"1":` as the string "1"."""
    yaml_data = {"jobs": {1: {"name": "Int"}, "1": {"name": "Str"}}, "edges": {}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert sorted(job["name"] for job in yaml_data["jobs"].values()) == ["Int", "Str"]


@pytest.mark.usefixtures("ascii_mode")
def test_a_boolean_edge_key_does_not_raise() -> None:
    """An unquoted `on:` in the YAML parses as True, not a string."""
    yaml_data = {"jobs": {"x": {"name": "X"}}, "edges": {True: {"condition_type": "always"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert list(yaml_data["edges"]) == ["True"]


# --- the collision suffix lives inside the cap --------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_two_edges_between_two_maximal_names_stay_inside_the_key_cap(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """Capping first and appending the suffix after gave a 204-grapheme key."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    first, second = "a" * MAX_NAME_LENGTH, "b" * MAX_NAME_LENGTH
    yaml_data = {
        "jobs": {first: {"name": "A"}, second: {"name": "B"}},
        "edges": {
            "e1": {"source_job": first, "target_job": second, "n": 1},
            "e2": {"source_job": first, "target_job": second, "n": 2},
        },
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert sorted(e["n"] for e in yaml_data["edges"].values()) == [1, 2]
    for edge_key in yaml_data["edges"]:
        assert grapheme_length(edge_key) <= MAX_EDGE_KEY_LENGTH
    assert_no_special_chars(yaml_data, context=f"mode={mode}")


# --- by-name resolution must not bind to the wrong step ------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_a_nameless_job_and_an_empty_reference_do_not_bind() -> None:
    """`str(job_data.get("name"))` gave "None" for a job with no name, and
    `str(reference)` gave "None" for an empty `source_job:`, so they matched
    and the edge bound to a fabricated step."""
    yaml_data = {
        "jobs": {"a": {}, "b": {"name": "B"}},
        "edges": {"e": {"source_job": "", "target_job": "b"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] != "a"
    assert edge["source_job"] == AnthropicClient.UNRESOLVED_REFERENCE


@pytest.mark.usefixtures("ascii_mode")
def test_by_name_resolution_uses_the_name_the_model_wrote() -> None:
    """Matching after sanitizing folded `Résumé` and `Resume` together, so
    which step an edge bound to depended on document order."""
    yaml_data = {
        "jobs": {"k1": {"name": "Résumé"}, "k2": {"name": "Resume"}},
        "edges": {"e": {"source_job": "Resume", "target_job": "k1"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] == "k2"


@pytest.mark.usefixtures("ascii_mode")
def test_by_name_resolution_is_order_independent() -> None:
    """The same workflow with the two jobs the other way round."""
    yaml_data = {
        "jobs": {"k2": {"name": "Resume"}, "k1": {"name": "Résumé"}},
        "edges": {"e": {"source_job": "Resume", "target_job": "k1"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] == "k2"


@pytest.mark.usefixtures("ascii_mode")
def test_a_boolean_reference_does_not_bind_to_an_int_key() -> None:
    """`hash(True) == hash(1)`, so keying the mapping on the raw key swapped
    str shadowing for hash shadowing."""
    yaml_data = {
        "jobs": {1: {"name": "One"}},
        "edges": {"e": {"source_job": True, "target_job": 1}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["target_job"] in yaml_data["jobs"]
    assert edge["source_job"] != edge["target_job"]


# --- preservation goes through the same walker as redaction --------------------

LIGHTNING_EXPORT = """\
name: my-project
workflows:
  my-workflow:
    jobs:
      a:
        name: A
        body: |
          const SECRET_X = 'leak-me';
"""






def test_the_normal_shape_keeps_its_placeholder_naming() -> None:
    """The prompt tells the model placeholders look like `__CODE_BLOCK_<job>__`."""
    preserved, _ = AnthropicClient.extract_and_preserve_components(
        yaml.safe_load("jobs:\n  fetch:\n    id: i\n    body: get('/x');\n"),
    )

    assert "__CODE_BLOCK_fetch__" in preserved
    assert preserved["__CODE_BLOCK_fetch__"] == "get('/x');"


# --- a sanitised reference must not bind to a real but wrong step --------------


@pytest.mark.usefixtures("unicode_mode")
def test_a_reference_in_a_different_normal_form_still_resolves_by_name() -> None:
    """The by-name map compared raw strings, so a name stored in NFD and a
    reference written in NFC were different strings and never matched."""
    nfd = unicodedata.normalize("NFD", "Résumé")
    nfc = unicodedata.normalize("NFC", "Résumé")
    yaml_data = {
        "jobs": {"k1": {"name": nfd}, "k2": {"name": "Other"}},
        "edges": {"e": {"source_job": nfc, "target_job": "k2"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] == "k1"


@pytest.mark.usefixtures("unicode_mode")
def test_a_reference_with_a_trailing_space_resolves_to_the_step() -> None:
    """The reference and the key are the same name written differently, so this
    edge is correct and must survive. Round six sent it to the sentinel."""
    yaml_data = {
        "jobs": {"fetch": {"name": "F"}},
        "edges": {"e": {"source_job": "fetch ", "target_job": "fetch"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] == "fetch"
    assert edge["target_job"] == "fetch"


@pytest.mark.usefixtures("ascii_mode")
def test_a_boolean_key_and_its_string_form_resolve_to_the_same_step() -> None:
    """`on:` parses as the boolean True and sanitizes to the string "True", so
    after sanitizing both references name the same, only, step. Binding them
    both to it is correct — the bug is binding across *different* steps, which
    the test below covers."""
    yaml_data = {
        "jobs": {True: {"name": "T"}},
        "edges": {"e": {"source_job": "True", "target_job": True}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] in yaml_data["jobs"]
    assert edge["target_job"] == edge["source_job"]


# --- null name, and an edge key with nothing to derive a label from ------------


@pytest.mark.usefixtures("ascii_mode")
def test_a_null_name_does_not_become_the_literal_string_none() -> None:
    yaml_data = {"jobs": {"a": {"name": None}}, "edges": {}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["a"]["name"] != "None"
    assert yaml_data["jobs"]["a"]["name"] is None


@pytest.mark.parametrize("mode", ["false", "true"])
def test_an_edge_key_with_no_endpoints_is_still_sanitised(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """It used to ship verbatim, NUL included — which crashes the insert on
    Lightning's side just as surely as a name would."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {"jobs": {"a": {"name": "A"}}, "edges": {"bad\x00key": {"enabled": True}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    for edge_key in yaml_data["edges"]:
        assert "\x00" not in edge_key


# --- exact match beats a fold, and ambiguity is refused ------------------------


@pytest.mark.usefixtures("ascii_mode")
@pytest.mark.parametrize("reverse", [False, True])
def test_an_exact_name_match_wins_over_a_fold(reverse: bool) -> None:
    """`Fetch Patients` and `fetch patients` fold together but are two names.

    Taking the first fold hit bound the edge to whichever came first in the
    document, so reversing the jobs flipped the binding.
    """
    jobs = [("upper", {"name": "Fetch Patients"}), ("lower", {"name": "fetch patients"})]
    if reverse:
        jobs.reverse()
    yaml_data = {
        "jobs": dict(jobs),
        "edges": {"e": {"source_job": "fetch patients", "target_job": "upper"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] == "lower"


@pytest.mark.usefixtures("ascii_mode")
def test_an_ambiguous_name_reference_is_refused_not_guessed() -> None:
    """Two names that fold together and neither matches exactly. A visible
    dangle beats a silent binding to the wrong step."""
    yaml_data = {
        "jobs": {"a": {"name": "Fetch Patients"}, "b": {"name": "fetch-patients"}},
        "edges": {"e": {"source_job": "FETCH PATIENTS", "target_job": "a"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] not in ("a", "b")


# --- the sentinel guard must not destroy correct edges -------------------------


@pytest.mark.parametrize(
    ("mode", "job_key"),
    [
        ("false", "fetch "),
        ("false", "fetch\t"),
        ("false", "fetch\x00"),
        ("true", "fetch "),
        ("true", "fetch\x00"),
    ],
)
def test_a_key_that_sanitises_to_the_reference_still_resolves(
    monkeypatch: pytest.MonkeyPatch, mode: str, job_key: str,
) -> None:
    """Round six pushed these onto the sentinel. The key and the reference are
    the same name written differently, so the edge was right and got destroyed."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    yaml_data = {
        "jobs": {job_key: {"name": "F"}},
        "edges": {"e": {"source_job": "fetch", "target_job": "fetch"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] == "fetch"
    assert edge["source_job"] in yaml_data["jobs"]


@pytest.mark.usefixtures("unicode_mode")
def test_a_key_in_a_different_normal_form_still_resolves() -> None:
    nfd = unicodedata.normalize("NFD", "fetché")
    nfc = unicodedata.normalize("NFC", "fetché")
    yaml_data = {
        "jobs": {nfd: {"name": "F"}},
        "edges": {"e": {"source_job": nfc, "target_job": nfc}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    edge = next(iter(yaml_data["edges"].values()))
    assert edge["source_job"] in yaml_data["jobs"]


# --- the backstop must not delete the user's code ------------------------------




def test_an_unresolvable_placeholder_becomes_the_empty_marker() -> None:
    """Losing the code is bad; shipping a swap token the user will save is worse."""
    data = yaml.safe_load("jobs:\n  a:\n    body: __CODE_BLOCK_job_gone__\n")

    client = AnthropicClient.__new__(AnthropicClient)
    AnthropicClient.restore_components(client, data, {})

    assert data["jobs"]["a"]["body"] == "// Add operations here"




# --- a block-scalar placeholder must not ship as the user's code ---------------






def test_an_unknown_block_scalar_placeholder_does_not_ship() -> None:
    """No preserved value for it. Losing the code is bad; shipping a token the
    user will save is worse — that is the state origin/main did not reach."""
    data = {"jobs": {"a": {"body": "__CODE_BLOCK_gone__\n"}}}

    client = AnthropicClient.__new__(AnthropicClient)
    AnthropicClient.restore_components(client, data, {})

    assert data["jobs"]["a"]["body"] == "// Add operations here"


# --- an exact name match is not automatically unique --------------------------


@pytest.mark.usefixtures("ascii_mode")
@pytest.mark.parametrize("reverse", [False, True])
def test_two_jobs_sharing_a_name_are_refused_not_ordered(reverse: bool) -> None:
    """`_unique_name` in this same class exists because two jobs can arrive
    sharing a name. The exact-match loop took the first hit, so the binding
    flipped with document order."""
    jobs = [("first", {"name": "Fetch Data"}), ("second", {"name": "Fetch Data"})]
    if reverse:
        jobs.reverse()
    yaml_data = {
        "jobs": dict(jobs),
        "edges": {"e": {"source_job": "Fetch Data", "target_job": "first"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] not in ("first", "second")


# --- a decorated placeholder must not ship either ------------------------------

DECORATED_PLACEHOLDERS = {
    "fenced code block": "```\n__CODE_BLOCK_fetch__\n```",
    "inline backticks": "`__CODE_BLOCK_fetch__`",
    "line comment": "// __CODE_BLOCK_fetch__",
    "byte order mark": "\ufeff__CODE_BLOCK_fetch__",
    "zero width space": "\u200b__CODE_BLOCK_fetch__",
    "quoted": '"__CODE_BLOCK_fetch__"',
    "key prefix": "code: __CODE_BLOCK_fetch__",
    "token then code": "__CODE_BLOCK_fetch__\nfn(s => s);",
}










@pytest.mark.parametrize("body", ["__CODE_BLOCK_gone__", "__CODE_BLOCK_gone__\n", "```\n__CODE_BLOCK_gone__\n```"])
def test_a_token_we_never_issued_still_degrades(body: str) -> None:
    """Nothing to restore it from, and shipping it puts a swap token in front
    of the user as if it were their code."""
    parsed = {"jobs": {"a": {"id": "i", "body": body}}}

    client = AnthropicClient.__new__(AnthropicClient)
    client.validate_adaptors = lambda _data: None
    out = AnthropicClient.finalize_yaml(client, parsed, {})

    assert "__CODE_BLOCK_" not in out
    assert "Add operations here" in out




# --- non-string job names -----------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_non_string_names_are_coerced_and_sanitised() -> None:
    """`name: 2024`, `name: on` and `name: 01` are ordinary model output, and
    YAML hands them over as an int, a bool and an int.

    A string-only filter left them unsanitized and unrenamed, and Ecto rejects
    a `:string` cast from an integer — so a workflow that used to save stopped
    saving. Base coerced with `str(...)` first.
    """
    yaml_data = {
        "jobs": {
            "s1": {"name": 2024},
            "s2": {"name": True},
            "s3": {"name": 1},
        },
        "edges": {},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    names = [job["name"] for job in yaml_data["jobs"].values()]
    assert all(isinstance(name, str) for name in names), names
    assert names == ["2024", "True", "1"]


@pytest.mark.usefixtures("ascii_mode")
def test_an_edge_resolves_a_non_string_name() -> None:
    """The by-name map had the same filter, so an edge referencing such a job
    by name never resolved."""
    yaml_data = {
        "jobs": {"s1": {"name": 2024}, "s2": {"name": "Other"}},
        "edges": {"e": {"source_job": "2024", "target_job": "s2"}},
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert next(iter(yaml_data["edges"].values()))["source_job"] == "s1"


@pytest.mark.usefixtures("ascii_mode")
def test_a_null_name_is_still_left_alone() -> None:
    """The filter was written for this case, and it is the only one it was
    right about: `str(None)` is the literal name "None"."""
    yaml_data = {"jobs": {"a": {"name": None}}, "edges": {}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["a"]["name"] is None


# --- restoring must not discard the code around the token ----------------------






# --- two tokens in one body ----------------------------------------------------




def test_two_tokens_we_never_issued_do_not_ship() -> None:
    data = {"jobs": {"a": {"id": "i", "body": "__CODE_BLOCK_x__\n__CODE_BLOCK_y__"}}}

    client = AnthropicClient.__new__(AnthropicClient)
    AnthropicClient.restore_components(client, data, {})

    assert "__CODE_BLOCK_" not in data["jobs"]["a"]["body"]


# --- claims -------------------------------------------------------------------






# --- a job key containing `__` ------------------------------------------------




def test_a_truncated_prefix_sibling_is_not_spliced_in() -> None:
    """With a second job whose key is the truncated prefix, the short match
    picked that job's body instead."""
    data = {"jobs": {"sync__patients": {"id": "i", "body": "__CODE_BLOCK_sync__patients__"}}}
    preserved = {"__CODE_BLOCK_sync__": "WRONG();", "__CODE_BLOCK_sync__patients__": "RIGHT();"}

    client = AnthropicClient.__new__(AnthropicClient)
    AnthropicClient.restore_components(client, data, preserved)

    assert data["jobs"]["sync__patients"]["body"] == "RIGHT();"




# --- a block comment must not leave the step inert -----------------------------




# --- a non-string body anywhere in the tree ------------------------------------






# --- prefix-pair token texts ---------------------------------------------------






