"""Records, metrics and winner selection for the web-tools experiment."""

from dataclasses import dataclass, field
from statistics import mean

from .trace import count

# Approximate list prices for the planner's model (claude-opus via models.py),
# in $ per token. Subagent calls not included.
PRICE_INPUT = 5 / 1_000_000
PRICE_OUTPUT = 25 / 1_000_000
PRICE_CACHE_WRITE = PRICE_INPUT * 1.25
PRICE_CACHE_READ = PRICE_INPUT * 0.1
# Web search bills per search.
PRICE_SEARCH = 10 / 1000

# Straight apostrophe for matching.
RIGHT_SINGLE_QUOTE = chr(0x2019)

NUMERIC = (
    "web_calls", "refused_prior", "refused_allowlist", "followup_fetches",
    "input_tokens", "seconds", "cost",
)

# Stage -> (metric averaged over non-control scenarios, True when lower is better).
PRIMARY = {1: ("refused_prior", True), 2: ("grounded_rate", False), 3: ("followup_fetches", True)}


@dataclass
class TurnRecord:
    answer: str
    trace: list[dict]
    usage: dict
    seconds: float
    rounds: int
    downgraded: bool = False
    error: str | None = None


@dataclass
class RunRecord:
    scenario_id: str
    variant: str
    run_index: int
    turns: list[TurnRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        turns = [TurnRecord(**t) for t in data["turns"]]
        return cls(data["scenario_id"], data["variant"], data["run_index"], turns)


def is_grounded(answer: str, trace: list[dict], facts: tuple[str, ...]) -> bool:
    """Every fact is in the answer and in a fetched page, so it was read, not remembered."""
    return all(norm(fact) in norm(answer) for fact in facts) and facts_fetched(trace, facts)


def facts_fetched(trace: list[dict], facts: tuple[str, ...]) -> bool:
    """Every fact appears in some fetched page: the truncation signal, independent of the answer."""
    pages = fetched_pages(trace)
    return all(any(norm(fact) in page for page in pages) for fact in facts)


def run_metrics(run: RunRecord, facts: tuple[str, ...]) -> dict:
    trace = [call for turn in run.turns for call in turn.trace]
    answers = "\n".join(turn.answer for turn in run.turns)
    return {
        "web_calls": count(trace, tool="search") + count(trace, tool="fetch"),
        "refused_prior": count(trace, result="url_not_in_prior_context"),
        "refused_allowlist": count(trace, result="url_not_allowed"),
        "followup_fetches": sum(count(turn.trace, tool="fetch") for turn in run.turns[1:]),
        "grounded": is_grounded(answers, trace, facts) if facts else None,
        "fact_fetched": facts_fetched(trace, facts) if facts else None,
        "input_tokens": sum(
            turn.usage.get(key, 0)
            for turn in run.turns
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        ),
        "seconds": sum(turn.seconds for turn in run.turns),
        "cost": sum(turn_cost(turn) for turn in run.turns),
    }


def summarise(runs: list[RunRecord], facts: tuple[str, ...], source_page: str | None = None) -> dict:
    """Mean metrics over the valid runs. Failed and downgraded runs are counted."""
    valid = [run for run in runs if not failed(run) and not downgraded(run)]
    rows = [run_metrics(run, facts) for run in valid]
    summary: dict = {
        "n": len(runs),
        "valid": len(valid),
        "errors": sum(1 for run in runs if failed(run)),
        "downgraded": sum(1 for run in runs if downgraded(run) and not failed(run)),
    }
    for key in NUMERIC:
        summary[key] = mean(r[key] for r in rows) if rows else None
    summary["web_calls_max"] = max(run_metrics(run, facts)["web_calls"] for run in runs) if runs else None
    summary["grounded_rate"] = mean(r["grounded"] for r in rows) if rows and facts else None
    summary["fact_fetched_rate"] = mean(r["fact_fetched"] for r in rows) if rows and facts else None
    summary["source_page_rate"] = (
        mean(fetched_source(run, source_page) for run in valid) if valid and source_page else None
    )
    return summary


def pick_winner(
    stage: int,
    table: dict[str, dict[str, dict]],
    controls: list[str],
    complexity: dict[str, int],
) -> tuple[str | None, list[str]]:
    """Apply the spec's winner rules in order and say why at each step.

    1. Disqualify a variant if a control run used the web, or if it has more
       allowlist refusals than the carried-forward variant (the table's first key).
    2. Rank by the stage's primary metric over the non-control scenarios.
    3. Break ties by input tokens, then seconds, then the simpler change.
    """
    reasons: list[str] = []
    baseline = next(iter(table))
    base_allowlist = sum(r.get("refused_allowlist") or 0 for r in table[baseline].values())
    metric, lower_is_better = PRIMARY[stage]

    eligible = []
    for variant, rows in table.items():
        if any(not s.get("valid") for s in rows.values()):
            reasons.append(f"{variant}: disqualified, a scenario has no valid runs")
            continue
        if any((rows[s].get("web_calls_max") or 0) > 0 for s in controls if s in rows):
            reasons.append(f"{variant}: disqualified, a control run used the web")
            continue
        if sum(r.get("refused_allowlist") or 0 for r in rows.values()) > base_allowlist:
            reasons.append(f"{variant}: disqualified, more allowlist refusals than {baseline}")
            continue
        eligible.append(variant)

    if not eligible:
        return None, reasons

    def rank(variant: str) -> tuple:
        rows = table[variant]
        scored = [s for s in rows if s not in controls]
        primary = round(mean_over(rows, scored, metric), 2)
        return (
            primary if lower_is_better else -primary,
            round(mean_over(rows, scored, "input_tokens")),
            round(mean_over(rows, scored, "seconds"), 1),
            complexity.get(variant, 0),
        )

    for variant in eligible:
        primary, tokens, seconds, simplicity = rank(variant)
        reasons.append(
            f"{variant}: {metric}={abs(primary)} input_tokens={tokens} seconds={seconds} complexity={simplicity}",
        )
    return min(eligible, key=rank), reasons


def format_table(table: dict[str, dict[str, dict]]) -> str:
    header = (
        "| variant | scenario | valid/n | web calls | refused prior | refused allowlist "
        "| grounded | fact fetched | source page | follow-up fetches | input tok | sec | $ |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for variant, rows in table.items():
        for scenario_id, s in rows.items():
            lines.append(
                f"| {variant} | {scenario_id} | {s['valid']}/{s['n']} | {cell(s['web_calls'])} "
                f"| {cell(s['refused_prior'])} | {cell(s['refused_allowlist'])} "
                f"| {cell(s['grounded_rate'])} | {cell(s['fact_fetched_rate'])} | {cell(s['source_page_rate'])} "
                f"| {cell(s['followup_fetches'])} | {cell(s['input_tokens'], 0)} "
                f"| {cell(s['seconds'], 1)} | {cell(s['cost'], 3)} |",
            )
    return "\n".join(lines)


def norm(text: str) -> str:
    return " ".join(text.replace(RIGHT_SINGLE_QUOTE, "'").lower().split())


def fetched_pages(trace: list[dict]) -> list[str]:
    return [norm(call["content"]) for call in trace if call.get("content")]


def fetched_source(run: RunRecord, source_page: str) -> bool:
    return any(
        call["tool"] == "fetch" and call["result"] == "ok" and source_page in call["target"]
        for turn in run.turns
        for call in turn.trace
    )


def turn_cost(turn: TurnRecord) -> float:
    usage = turn.usage
    return (
        usage.get("input_tokens", 0) * PRICE_INPUT
        + usage.get("output_tokens", 0) * PRICE_OUTPUT
        + usage.get("cache_creation_input_tokens", 0) * PRICE_CACHE_WRITE
        + usage.get("cache_read_input_tokens", 0) * PRICE_CACHE_READ
        + count(turn.trace, tool="search") * PRICE_SEARCH
    )


def failed(run: RunRecord) -> bool:
    return any(turn.error for turn in run.turns)


def downgraded(run: RunRecord) -> bool:
    return any(turn.downgraded for turn in run.turns)


def mean_over(rows: dict[str, dict], scenarios: list[str], key: str) -> float:
    values = [rows[s][key] for s in scenarios if rows[s].get(key) is not None]
    return mean(values) if values else 0.0


def cell(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)
