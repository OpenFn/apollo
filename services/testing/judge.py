"""LLM-as-judge for acceptance tests.

Evaluates a chat service's response against a small list of natural-language
criteria, returning a structured verdict.

Three layers feed the judge prompt:
1. Universal rules — loaded from `judge_rules.md` next to this file. Apply to
   every evaluation. Edit the markdown file to change them; no Python touched.
2. Per-test criteria — passed in via `evaluate(criteria=[...])`.
3. Open-ended "flag anything else notable" — hardcoded at the end of the
   prompt. Means the criteria list never has to be exhaustive.

Usage:
    from testing import judge

    verdict = judge.evaluate(
        criteria=["The response uses British English spelling.", ...],
        candidate=response_dict,
        test_notes=__doc__,
    )
    assert verdict.passed, verdict.summary
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from anthropic import Anthropic


DEFAULT_MODEL = "claude-sonnet-4-5"
_RULES_PATH = Path(__file__).parent / "judge_rules.md"


@dataclass
class CriterionResult:
    criterion: str
    passed: bool
    reasoning: str


@dataclass
class GeneralFlag:
    description: str
    severity: str  # "note" or "regression"


@dataclass
class Verdict:
    passed: bool
    score: float
    criteria: list[CriterionResult]
    general_flags: list[GeneralFlag]
    summary: str
    judge_usage: dict = field(default_factory=dict)


def _load_universal_rules() -> str:
    """Read the universal-rules markdown file. Empty string if absent or empty."""
    if not _RULES_PATH.exists():
        return ""
    text = _RULES_PATH.read_text().strip()
    return text


def _build_system_prompt() -> str:
    universal = _load_universal_rules()
    parts = [
        "You are a strict but fair quality reviewer for an AI assistant's responses.",
        "You will be given (a) optional universal rules that apply to every response, "
        "(b) a list of test-specific criteria, and (c) the AI assistant's full response "
        "to evaluate.",
        "",
        "Return JSON with this exact shape:",
        "{",
        '  "criteria": [{"criterion": str, "passed": bool, "reasoning": str}, ...],',
        '  "general_flags": [{"description": str, "severity": "note" | "regression"}, ...]',
        "}",
        "",
        "For each listed criterion, return one object in the same order as given.",
        "",
        "Additionally, flag anything else in the response that looks like a problem — "
        "tone drift, hedging, hallucinated facts, leaked secrets or API keys, broken "
        "formatting, factual errors, or anything else that would make a reviewer "
        "pause — even if no criterion covers it. Mark each flag with severity:",
        "  - 'note': minor or informational",
        "  - 'regression': would surprise a reviewer or hurt a user",
        "If nothing is notable, return an empty general_flags array.",
    ]
    if universal:
        parts += [
            "",
            "UNIVERSAL RULES (apply to every response):",
            universal,
        ]
    return "\n".join(parts)


def _build_user_prompt(
    criteria: list[str],
    candidate: dict,
    test_notes: Optional[str],
) -> str:
    parts = []
    if test_notes:
        parts += [
            "TEST CONTEXT (background; do not grade against this directly):",
            test_notes.strip(),
            "",
        ]
    parts += ["CRITERIA TO EVALUATE:"]
    if criteria:
        for i, c in enumerate(criteria, 1):
            parts.append(f"  {i}. {c}")
    else:
        parts.append("  (none — rely on universal rules and general_flags only)")
    parts += [
        "",
        "CANDIDATE RESPONSE (the AI assistant's full output, as JSON):",
        json.dumps(candidate, indent=2, default=str),
    ]
    return "\n".join(parts)


def _parse_verdict(
    raw_text: str,
    criteria: list[str],
    usage: dict,
) -> Verdict:
    """Parse JSON judge output into a Verdict. Lenient: missing fields → defaults."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return Verdict(
            passed=False,
            score=0.0,
            criteria=[],
            general_flags=[GeneralFlag(description=f"judge_error: {e}", severity="regression")],
            summary=f"judge_error: failed to parse JSON output\n---\n{raw_text[:500]}",
            judge_usage=usage,
        )

    raw_criteria = data.get("criteria", [])
    parsed_criteria = []
    for i, criterion_text in enumerate(criteria):
        if i < len(raw_criteria):
            entry = raw_criteria[i]
            parsed_criteria.append(CriterionResult(
                criterion=criterion_text,
                passed=bool(entry.get("passed", False)),
                reasoning=str(entry.get("reasoning", "")),
            ))
        else:
            parsed_criteria.append(CriterionResult(
                criterion=criterion_text,
                passed=False,
                reasoning="judge_error: no verdict returned for this criterion",
            ))

    raw_flags = data.get("general_flags", []) or []
    parsed_flags = [
        GeneralFlag(
            description=str(f.get("description", "")),
            severity=str(f.get("severity", "note")),
        )
        for f in raw_flags
    ]

    all_criteria_passed = all(c.passed for c in parsed_criteria) if parsed_criteria else True
    has_regression = any(f.severity == "regression" for f in parsed_flags)
    passed = all_criteria_passed and not has_regression
    score = (sum(1 for c in parsed_criteria if c.passed) / len(parsed_criteria)) if parsed_criteria else 1.0

    summary = _format_summary(parsed_criteria, parsed_flags, passed)

    return Verdict(
        passed=passed,
        score=score,
        criteria=parsed_criteria,
        general_flags=parsed_flags,
        summary=summary,
        judge_usage=usage,
    )


def _format_summary(criteria: list[CriterionResult], flags: list[GeneralFlag], passed: bool) -> str:
    lines = [f"Verdict: {'PASS' if passed else 'FAIL'}"]
    if criteria:
        lines.append("")
        lines.append("Criteria:")
        for c in criteria:
            mark = "✓" if c.passed else "✗"
            lines.append(f"  {mark} {c.criterion}")
            if c.reasoning:
                lines.append(f"      → {c.reasoning}")
    if flags:
        lines.append("")
        lines.append("General flags:")
        for f in flags:
            lines.append(f"  [{f.severity}] {f.description}")
    return "\n".join(lines)


def evaluate(
    *,
    criteria: list[str],
    candidate: dict,
    test_notes: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    client: Optional[Anthropic] = None,
) -> Verdict:
    """Evaluate a candidate response against criteria using an LLM judge.

    Args:
        criteria: List of natural-language criteria. Can be empty — universal
            rules and general_flags still apply.
        candidate: Full response dict from the chat service. Whatever it
            contains is shown verbatim to the judge.
        test_notes: Optional background context (typically the test's __doc__).
            Shown to the judge but not graded against directly.
        model: Judge model. Defaults to Sonnet.
        client: Optional Anthropic client. Constructed from env if not given.

    Returns:
        A Verdict. Test code typically asserts on verdict.passed and uses
        verdict.summary as the failure message.
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "judge.evaluate requires ANTHROPIC_API_KEY. "
                "Acceptance tests are run on demand against real models."
            )
        client = Anthropic(api_key=api_key)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(criteria, candidate, test_notes)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": "{"},  # prefill to force JSON
        ],
    )

    raw_text = "{" + response.content[0].text
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return _parse_verdict(raw_text, criteria, usage)
