"""LLM-as-judge for acceptance tests.

Evaluates a chat service's response against a small list of natural-language
criteria, returning a structured verdict.

Each evaluation runs under a named judge (configured in
`services/testing/judges/<name>.md` — see `services/testing/judges.py`).
Different judges have different role and rules, but share the same JSON output
contract.

Three layers feed the judge prompt:
1. Judge role + universal rules — loaded from the judge's MD config.
2. Per-test criteria — passed in via `evaluate(criteria=[...])`.
3. Open-ended "flag anything else notable" — hardcoded at the end of the
   prompt. Means the criteria list never has to be exhaustive.

Usage:
    from testing import judge

    verdict = judge.evaluate(
        criteria=["The response uses British English spelling.", ...],
        candidate=response_dict,
        test_notes=__doc__,
        judge="general",
    )
    assert verdict.passed, verdict.summary
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from anthropic import Anthropic

from models import CLAUDE_FABLE
from testing.judges import load_judge


DEFAULT_MODEL = CLAUDE_FABLE
DEFAULT_JUDGE = "general"


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
    judge_name: str = DEFAULT_JUDGE


def _build_system_prompt(judge_name: str) -> str:
    config = load_judge(judge_name)
    parts = [config.role.strip()]
    parts += [
        "",
        "Respond with ONLY a JSON object, no prose, no markdown fences. The object "
        "must have this exact shape:",
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
    if config.rules:
        parts += [
            "",
            "UNIVERSAL RULES (apply to every response):",
            config.rules,
        ]
    return "\n".join(parts)


def _build_user_prompt(
    criteria: list[str],
    candidate: dict,
    test_notes: Optional[str],
    request: Optional[dict],
) -> str:
    parts = []
    if test_notes:
        parts += [
            "TEST CONTEXT (background; do not grade against this directly):",
            test_notes.strip(),
            "",
        ]
    if request:
        parts += [
            "ORIGINAL REQUEST sent to the service (use as ground truth for what existed before and what was asked):",
            json.dumps(request, indent=2, default=str),
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


def _extract_json_object(text: str) -> Optional[dict]:
    """Find and parse the first top-level JSON object in text.

    Tolerates markdown fences and leading/trailing prose. Returns None if no
    parseable object is found.
    """
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _parse_verdict(
    raw_text: str,
    criteria: list[str],
    usage: dict,
    judge_name: str,
) -> Verdict:
    data = _extract_json_object(raw_text)
    if data is None:
        return Verdict(
            passed=False,
            score=0.0,
            criteria=[],
            general_flags=[GeneralFlag(description="judge_error: no JSON object in output", severity="regression")],
            summary=f"judge_error ({judge_name}): no JSON object found in output\n---\n{raw_text[:500]}",
            judge_usage=usage,
            judge_name=judge_name,
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

    summary = _format_summary(judge_name, parsed_criteria, parsed_flags, passed)

    return Verdict(
        passed=passed,
        score=score,
        criteria=parsed_criteria,
        general_flags=parsed_flags,
        summary=summary,
        judge_usage=usage,
        judge_name=judge_name,
    )


def _format_summary(judge_name: str, criteria: list[CriterionResult], flags: list[GeneralFlag], passed: bool) -> str:
    lines = [f"Verdict ({judge_name}): {'PASS' if passed else 'FAIL'}"]
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
        lines.append("Flags raised by the judge:")
        for f in flags:
            lines.append(f"  ✗ [{f.severity}] {f.description}")
    return "\n".join(lines)


def evaluate(
    *,
    criteria: list[str],
    candidate: dict,
    test_notes: Optional[str] = None,
    request: Optional[dict] = None,
    judge: str = DEFAULT_JUDGE,
    model: str = DEFAULT_MODEL,
    client: Optional[Anthropic] = None,
) -> Verdict:
    """Evaluate a candidate response under a named judge.

    Args:
        criteria: Test-specific bullets the judge grades against.
        candidate: Full response dict from the chat service.
        test_notes: Optional background context (typically the test's __doc__).
            Shown to the judge but not graded directly.
        request: Optional original request payload sent to the service. When
            provided, the judge can ground "before vs after" reasoning in the
            actual inputs (workflow_yaml, current turn, history) instead of
            guessing.
        judge: Name of the judge (file at services/testing/judges/<name>.md).
            Defaults to "general".
        model: Model to use. Defaults to CLAUDE_FABLE from services/models.py.
        client: Optional Anthropic client. Constructed from env if not given.

    Returns:
        A Verdict. Test code asserts on verdict.passed and uses verdict.summary
        as the failure message.
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "judge.evaluate requires ANTHROPIC_API_KEY. "
                "Acceptance tests are run on demand against real models."
            )
        client = Anthropic(api_key=api_key)

    system_prompt = _build_system_prompt(judge)
    user_prompt = _build_user_prompt(criteria, candidate, test_notes, request)

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )

    # First text block, not content[0]: Fable always thinks, so the
    # response may lead with a thinking block.
    raw_text = next((b.text for b in response.content if b.type == "text"), "")
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return _parse_verdict(raw_text, criteria, usage, judge)
