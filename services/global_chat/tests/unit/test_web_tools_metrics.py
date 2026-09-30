"""Unit tests for web-tools experiment metrics and winner selection."""

from global_chat.tests.web_tools.metrics import (
    RunRecord,
    TurnRecord,
    facts_fetched,
    format_table,
    is_grounded,
    pick_winner,
    run_metrics,
    summarise,
)

USAGE = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
PAGE = "Patient.gender   0..1   male | female | other | unknown"


def fetch(result: str = "ok", content: str | None = PAGE) -> dict:
    call = {"round": 1, "tool": "fetch", "target": "https://hl7.org/fhir/R4/patient.html", "result": result}
    if result == "ok":
        call["content"] = content
        call["content_chars"] = len(content) if content else None
    return call


def turn(trace: list[dict], answer: str = "gender is 0..1", **kwargs: object) -> TurnRecord:
    return TurnRecord(answer=answer, trace=trace, usage=USAGE, seconds=2.0, rounds=1, **kwargs)


def run(*turns: TurnRecord, index: int = 0) -> RunRecord:
    return RunRecord(scenario_id="s", variant="v", run_index=index, turns=list(turns))


def test_grounded_needs_the_fact_in_the_answer_and_in_a_fetched_page() -> None:
    assert is_grounded("Gender  is 0..1", [fetch()], ("0..1",))
    assert not is_grounded("gender is 0..1", [], ("0..1",))
    assert not is_grounded("gender is optional", [fetch()], ("0..1",))


def test_facts_fetched_ignores_the_answer() -> None:
    assert facts_fetched([fetch()], ("male | female",))
    assert not facts_fetched([fetch(content="truncated before the table")], ("male | female",))
    assert not facts_fetched([fetch("url_not_allowed")], ("male",))


def test_run_metrics_counts_refusals_and_followup_fetches() -> None:
    metrics = run_metrics(run(
        turn([fetch("url_not_in_prior_context"), {"round": 1, "tool": "search", "target": "q", "result": "ok"}, fetch()]),
        turn([fetch("url_not_allowed"), fetch()]),
    ), ("0..1",))

    assert {key: metrics[key] for key in ("web_calls", "refused_prior", "refused_allowlist", "followup_fetches")} == {
        "web_calls": 5,
        "refused_prior": 1,
        "refused_allowlist": 1,
        "followup_fetches": 2,
    }
    assert metrics["grounded"] is True
    assert (metrics["input_tokens"], metrics["seconds"]) == (2 * USAGE["input_tokens"], 4.0)
    assert metrics["cost"] > 0


def test_run_metrics_leaves_fact_checks_empty_without_facts() -> None:
    metrics = run_metrics(run(turn([])), ())

    assert metrics["grounded"] is None
    assert metrics["fact_fetched"] is None


def test_summarise_excludes_failed_and_downgraded_runs_but_counts_them() -> None:
    summary = summarise([
        run(turn([fetch()]), index=0),
        run(turn([], error="APIStatusError: overloaded"), index=1),
        run(turn([], downgraded=True), index=2),
    ], ("0..1",))

    assert (summary["n"], summary["valid"], summary["errors"], summary["downgraded"]) == (3, 1, 1, 1)
    assert summary["web_calls"] == 1
    assert summary["grounded_rate"] == 1.0


def test_summarise_with_no_valid_runs_reports_none() -> None:
    summary = summarise([run(turn([], error="boom"))], ())

    assert summary["valid"] == 0
    assert summary["web_calls"] is None
    assert summary["web_calls_max"] is None


VALUESET = "http://hl7.org/fhir/R4/valueset-link-type.html"


def test_source_page_rate_counts_runs_that_fetched_the_named_page() -> None:
    """fhir_deep's facts also live on a short value-set page, so which page was read matters."""
    summary = summarise([
        run(turn([fetch()]), index=0),
        run(turn([{**fetch(), "target": VALUESET}]), index=1),
        run(turn([fetch("url_not_in_prior_context")]), index=2),
    ], ("0..1",), source_page="patient.html")

    assert summary["source_page_rate"] == 1 / len(["patient", "valueset", "refused"])


def test_source_page_rate_is_empty_without_a_source_page() -> None:
    assert summarise([run(turn([fetch()]))], ("0..1",))["source_page_rate"] is None


def row(**overrides: float) -> dict:
    base = {
        "n": 3, "valid": 3, "errors": 0, "downgraded": 0,
        "web_calls": 2.0, "web_calls_max": 2, "refused_prior": 0.0, "refused_allowlist": 0.0,
        "followup_fetches": 0.0, "input_tokens": 50000.0, "seconds": 30.0, "cost": 0.3,
        "grounded_rate": 1.0, "fact_fetched_rate": 1.0, "source_page_rate": None,
    }
    base.update(overrides)
    return base


CLEAN_CONTROL = row(web_calls=0.0, web_calls_max=0, grounded_rate=None, fact_fetched_rate=None)


def test_a_variant_whose_control_used_the_web_is_disqualified() -> None:
    table = {
        "base": {"control": CLEAN_CONTROL, "fhir": row(refused_prior=2.0)},
        "base+1a": {"control": row(web_calls_max=1), "fhir": row(refused_prior=0.0)},
    }

    winner, reasons = pick_winner(1, table, ["control"], {"base": 0, "base+1a": 1})

    assert winner == "base"
    assert any("base+1a" in r and "disqualified" in r for r in reasons)


def test_a_variant_that_adds_allowlist_refusals_is_disqualified() -> None:
    table = {
        "base": {"fhir": row(refused_prior=2.0)},
        "base+1b": {"fhir": row(refused_prior=0.0, refused_allowlist=1.0)},
    }

    winner, _ = pick_winner(1, table, [], {"base": 0, "base+1b": 2})

    assert winner == "base"


def test_stage_1_prefers_fewer_prior_context_refusals() -> None:
    table = {
        "base": {"control": CLEAN_CONTROL, "fhir": row(refused_prior=2.0)},
        "base+1a": {"control": CLEAN_CONTROL, "fhir": row(refused_prior=0.33)},
        "base+1b": {"control": CLEAN_CONTROL, "fhir": row(refused_prior=0.0)},
    }

    winner, _ = pick_winner(1, table, ["control"], {"base": 0, "base+1a": 1, "base+1b": 2})

    assert winner == "base+1b"


def test_stage_2_prefers_the_higher_grounded_rate() -> None:
    table = {"base": {"deep": row(grounded_rate=0.0)}, "base+25k": {"deep": row(grounded_rate=1.0)}}

    winner, _ = pick_winner(2, table, [], {"base": 0, "base+25k": 1})

    assert winner == "base+25k"


def test_ties_fall_to_input_tokens_then_simplicity() -> None:
    cheaper = {"base+1a": {"fhir": row(input_tokens=40000.0)}, "base+1b": {"fhir": row()}}
    assert pick_winner(1, cheaper, [], {"base+1a": 1, "base+1b": 2})[0] == "base+1a"

    even = {"base+1b": {"fhir": row()}, "base+1a": {"fhir": row()}}
    assert pick_winner(1, even, [], {"base+1a": 1, "base+1b": 2})[0] == "base+1a"


def test_format_table_has_one_row_per_variant_and_scenario() -> None:
    text = format_table({"base": {"fhir": row(), "control": CLEAN_CONTROL}})

    assert text.count("\n| base ") == len(["fhir", "control"])
    assert "refused prior" in text


def test_format_table_shows_the_source_page_rate() -> None:
    text = format_table({"base": {"fhir": row(source_page_rate=0.5)}})

    assert "source page" in text
    assert "| 0.50 |" in text
