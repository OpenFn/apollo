"""Runs the adaptor-knowledge cases against job_chat and asserts with regexes.

One pytest item per case. A failure names the doc location the answer should
have come from, so the output doubles as a worklist.

    poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s
    poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s -k interfaces

Every case costs one job_chat call against the live Anthropic API.
"""

import re

import pytest
from testing.apollo_client import ApolloClient

from .cases import ALL_CASES, Case
from .scoreboard import record


def _fenced_blocks(text: str) -> str:
    """Concatenate the contents of every ``` fence in text."""
    return "\n".join(re.findall(r"```(?:\w+)?\s*\n(.*?)```", text or "", re.DOTALL))


def _haystack(response: dict, target: str) -> str:
    """The text a case's regexes run against.

    "code" narrows to generated code — the suggested_code field plus any fenced
    blocks in the reply — so that prose *discussing* a wrong key ("you might
    expect text:, but...") cannot trip a `forbid`.
    """
    reply = response.get("response") or ""
    if target == "text":
        return reply
    return "\n".join([response.get("suggested_code") or "", _fenced_blocks(reply)])


def _build_payload(case: Case) -> dict:
    context: dict = {"adaptor": case.adaptor}
    if case.expression is not None:
        context["expression"] = case.expression
    return {
        "content": case.prompt,
        "context": context,
        "suggest_code": True,
        "meta": {"session_id": f"sess-adaptor-knowledge-{case.id}"},
    }


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_adaptor_knowledge(case: Case, require_adaptor_docs):
    require_adaptor_docs(case.adaptor)
    response = ApolloClient().call("job_chat", _build_payload(case))
    hay = _haystack(response, case.target)

    if not hay.strip():
        # Abstention cases assert only that something bad ISN'T generated, so
        # generating nothing is a pass. Everywhere else an empty haystack means
        # there was nothing to check and the result would be meaningless.
        if case.empty_target_passes:
            record(case.id, case.group, True)
            return
        record(case.id, case.group, False)
        pytest.fail(
            f"{case.id}: no {case.target} in the response to assert on.\n"
            f"  reply: {(response.get('response') or '')[:300]!r}",
        )

    # `expect` is case-insensitive and satisfied by ANY match: it asks whether a
    # concept is present, so it should be generous about how it's spelled.
    #
    # `forbid` is case-SENSITIVE, because it names a specific wrong identifier.
    # Matching loosely there is actively harmful — `fileName` would match the
    # correct `filename` under re.I and fail a passing case.
    missing = [p for p in case.expect if not re.search(p, hay, re.I)] if case.expect else []
    expect_failed = bool(case.expect) and len(missing) == len(case.expect)
    hits = [p for p in case.forbid if re.search(p, hay)]

    passed = not expect_failed and not hits
    record(case.id, case.group, passed)

    if passed:
        return

    problems = []
    if expect_failed:
        problems.append(f"none of the expected patterns matched: {case.expect}")
    for p in hits:
        problems.append(f"forbidden pattern matched: {p!r}")

    pytest.fail(
        "\n".join(
            [
                f"{case.id}  [{case.group}]  {case.adaptor}",
                *(f"  - {p}" for p in problems),
                f"  documented at: {case.doc_ref}",
                f"  expected failure mode: {case.why}",
                f"  --- {case.target} ---",
                hay[:1200],
            ],
        ),
    )
