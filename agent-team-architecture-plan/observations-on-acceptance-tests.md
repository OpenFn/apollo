# Observations: re-reading `4-acceptance-tests.md` against the unit-tests / service-tests / overview decisions

**Branches consulted**

- `testing-architecture-unit-tests` — most polished, taken as authoritative.
- `testing-architecture-service-tests` — `2-service-tests.md` only.
- `5-overview.md` — identical on both branches; treated as the contract every section must obey.
- `4-acceptance-tests.md` — identical on both branches; the draft under review.

**TL;DR.** The acceptance draft is *mostly* aligned and not overly complex. It predates a couple of the unit-tests-branch decisions, so a small handful of details have drifted. None of it warrants a rewrite — call it five surgical edits plus one mild trim.

---

## 1. What the draft already gets right

These match the authoritative architecture without change:

- **Specs live under `services/<svc>/tests/acceptance/`** as a subfolder of the per-service flat `tests/` folder. Consistent with overview §2 and unit-tests-branch §2.
- **No top-level `tests/` tree, no `services/llm_evaluator/` service, no `golden/` git tree, no custom CLI runner.** All match overview §10 and unit-tests-branch §10.
- **Markdown specs collected by `pytest_collect_file`** registered in the root `apollo/conftest.py`. Matches overview §5.
- **Judge as a helper module, not a service.** Matches overview decisions and unit-tests-branch §3.
- **CI: human-triggered only, shared `llm-tests.yaml` workflow.** Matches overview §6.
- **Langfuse used lightly (sessions + scores), not as the runner.** Sane.

The draft also correctly *doesn't* lean on the `test_hooks` second-arg pattern — acceptance goes via HTTP, which strips it. This is implicit and could be made one-line explicit (see §3 below) but isn't a defect.

---

## 2. What needs to change (five surgical edits)

### 2.1 Make the location of `testing/` explicit

**Why this matters.** There are now two competing readings of where the shared test package lives:

- **Unit-tests branch + overview:** `apollo/testing/` — peer of `services/` and `platform/`, not a service. `pythonpath = ["services", "."]` lets `from testing.fixtures import ...` resolve.
- **Service-tests branch §7:** `services/testing/` — under `services/`, on the import path via `pythonpath = ["services"]`.

Per the user, the unit-tests branch is authoritative, so `apollo/testing/` (root-level peer) wins. The acceptance draft writes "`testing/`" in §2 and §5 without disambiguating; a casual reader of the service-tests branch would parse it the other way.

**Fix.** Replace every bare `testing/...` reference with `apollo/testing/...` once at the top of §2, then keep using the short form. Add a one-line note clarifying the location.

Affected lines: §2 (the `testing/` tree block, and the sentence "the judge helper and the markdown-spec pytest collector live in **`testing/`**"), §5 (header "`testing/judge.py`"), §6.2 step 2 (Scores API "directly from `judge.py`"), §15 ("Judge is a helper module").

### 2.2 The judge self-test in §5.4 is misclassified as `_unit`

The draft says:

> `services/tests/test_judge_unit.py` exercises the prompt builder and JSON parser with canned inputs. Uses `MockAnthropicClient` from the service tier's shared helpers.

That violates unit-tests-branch §1 rule 3:

> **Zero LLM calls**, not even through a mock HTTP client. If the test needs a mocked Anthropic response to make sense, it's a service test.

**Fix — pick one.** Either:

- **(a)** Split the self-tests by what they touch:
  - `apollo/testing/tests/test_judge_unit.py` — pure prompt builder + JSON parser, no mocks.
  - `apollo/testing/tests/test_judge_service.py` — end-to-end `evaluate()` against `MockAnthropic`.
- **(b)** Drop the unit/service distinction and call them `apollo/testing/tests/test_judge_service.py` only — the planner builder is small enough that exercising it via the mock is fine.

Either way, also resolve the second drift: where do tests for `apollo/testing/` itself live? The unit-tests branch §3 reserves `services/tests/test_<helper>_unit.py` for shared `services/util.py` helpers, which is a reasonable analogue but lives under `services/`. Tests for code in `apollo/testing/` arguably belong next to that code — `apollo/testing/tests/`. This is a one-paragraph decision the draft currently glosses.

### 2.3 How does the `acceptance` marker get applied?

The unit/service/integration tiers all rely on a `pytest_collection_modifyitems` hook that auto-marks by filename suffix (`_unit.py`, `_service.py`, `_integration.py`). Acceptance has no such suffix — items come from `.md` files in an `acceptance/` folder via the custom `SpecFile`/`SpecItem` collector.

The draft mentions `@pytest.mark.acceptance` in the comparison table (§13) but never says how it gets applied to the synthesised `SpecItem`s. Right now the only mechanism is implicit — relying on `pytest -m acceptance` working off… nothing.

**Fix.** Add one sentence to §4 (right after the `SpecItem` definition):

> `SpecItem.__init__` calls `self.add_marker(pytest.mark.acceptance)` so `pytest -m acceptance` selects every spec item.

Or, equivalently, fold acceptance into the directory-based marker hook from overview §7 ("`acceptance/` folder name → `acceptance` marker"). Either path works; the draft just shouldn't leave it implicit.

### 2.4 Spell out that acceptance never uses `test_hooks`

`test_hooks` is *the* big architectural change in the service-tests branch. A reader landing on the acceptance plan after reading the others will look for it. One sentence in §1 or §13 closes the loop:

> Acceptance dispatches via HTTP through the running bun server, so `test_hooks` (service-tier only) is not threaded — every call hits the real production code path with real LLM responses.

This is a free clarification — the draft already implies it but never names it.

### 2.5 The `pyproject` markers need acceptance's marker declared

Unit-tests-branch §4 lists four markers:

```toml
markers = [
  "unit: ...",
  "service: ...",
  "integration: ...",
  "acceptance: LLM-judged quality/voice tests",
]
```

The acceptance draft doesn't restate this — fine — but with `--strict-markers` set in service-tests-branch §8's pytest config, an undeclared `acceptance` marker would fail collection. Worth a one-line cross-reference: "the `acceptance` marker is declared in `pyproject.toml`'s `[tool.pytest.ini_options].markers` block (see overview §5 / unit-tests §4)."

---

## 3. Where the plan could be lighter (mild trim)

The draft is 377 lines across 15 sections. Most of it earns its keep, but a few places over-describe:

- **§5.2 Prompt strategy** — the four bullets (system prompt, user prompt, prefilled `{`, malformed-JSON handling) are implementation details that belong in the judge's docstring or a follow-up implementation PR description. Cut to one line: "Judge prompt forces JSON via prefill and demands per-criterion verdict + verbatim evidence; bad JSON → `passed=False, reason='judge_error'`."
- **§7 Multi-run sampling** — the "no policies, no `2-of-3`" paragraph repeats §1 principle 6 ("humans decide"). One sentence: "Each of the N runs is a separate pytest item, judged independently; `pytest_sessionfinish` prints `<spec-id>: <k>/<N> passed` and exits with the standard pass/fail code per item." Lose the rest.
- **§10 Acceptance CI YAML** — fully duplicates the integration tier's YAML structure from `3-integration-tests.md` §9. Replace with: "Same shape as integration job (see `3-integration-tests.md` §9); differences: trigger condition (`run-acceptance` label / `workflow_dispatch` only — no `push`), `LANGFUSE_TRACING=true` always, 45-min timeout."
- **§13 Relationship to integration** vs **§15 What this tier does NOT do** — the "no top-level `tests/`" / "no llm_evaluator service" / "no custom runner" bullets in §15 partially duplicate §13 and the per-tier comparison in overview §1. Could lose ~3 bullets.

Together these are ~50-70 lines of trim. Optional — none of it is wrong, just verbose against the now-tighter tone of the unit-tests and overview docs.

---

## 4. What does NOT need changing

I deliberately don't think these need touching:

- **Spec markdown format (§3).** Frontmatter + named sections is the right shape. Worth keeping all of `# question`, `# context`, `# must_include`, `# must_not_include`, `# assertions`, `# notes` — each pulls weight. Don't cut.
- **Judge `Verdict` dataclass (§5.1).** Necessary for the human review loop and Langfuse score push.
- **Multi-run sampling mechanism (§7) — the *mechanism*.** Just trim the discussion, not the feature.
- **Langfuse integration (§6) — the scope as drawn.** Score push + session tagging is the right minimum; the §6.3 "what we don't do" guardrail is genuinely useful.
- **Trigger model (§9).** "Never automatic, human-gated only" is the most important policy in the document and is well placed.

---

## 5. Folder-structure check against the unit-tests branch

The unit-tests-branch decision is:

```
services/<svc>/tests/                      # flat, one folder per service
  __init__.py
  conftest.py                              # auto-marker by filename suffix
  test_<module>_unit.py                    # tier 1
  test_<module>_service.py                 # tier 2
  test_<svc>_integration.py                # tier 3
  acceptance/                              # tier 4 — markdown specs only
    *.md
  fixtures/                                # optional per-service
```

The acceptance draft's §2 layout matches this exactly — `acceptance/` is the only deviation from "flat folder + filename suffix", which is the correct deviation because markdown specs aren't `test_*.py` files. **No restructuring required.**

(For reference: the *service-tests-branch* §6 shows tier subfolders — `unit/`, `service/`, `integration/`, `acceptance/`. That's an inconsistency on that branch, not in the acceptance draft. Per the user's brief, the unit-tests-branch wins; the acceptance draft is on the right side of that disagreement already.)

---

## 6. Sequencing observation (small)

Overview §9 lists the implementation order: scaffolding → unit → service → integration → acceptance. The acceptance plan §2 says the markdown collector hook is registered in the root `apollo/conftest.py` "from day one". Because the root `conftest.py` lands in the **scaffolding** PR (overview §9 step 1), the spec collector should also land in step 1 even though the *first acceptance spec* doesn't ship until step 5. A one-line note in §4 of the acceptance plan would make this explicit:

> The `pytest_collect_file` hook ships with the scaffolding PR (overview §9 step 1) so adding `acceptance/*.md` later is purely additive.

Optional but cheap.

---

## 7. Summary of the punch list

| # | Edit | Where | Size |
|---|------|-------|------|
| 1 | Disambiguate `testing/` → `apollo/testing/` | §2, §5, §6.2, §15 | 4 line edits |
| 2 | Fix judge self-test classification (`_unit` vs `_service`); decide where tests for `apollo/testing/` live | §5.4 | 1 paragraph |
| 3 | State how the `acceptance` marker gets applied to `SpecItem`s | §4 | 1 sentence |
| 4 | One sentence: acceptance does not use `test_hooks` | §1 or §13 | 1 sentence |
| 5 | Cross-reference the marker declaration in `pyproject.toml` | §1 or §15 | 1 sentence |
| 6 *(optional)* | Trim §5.2, §7, §10, §13/§15 overlap | §§5.2, 7, 10, 15 | -50 lines |
| 7 *(optional)* | Note collector hook lands in scaffolding PR | §4 | 1 sentence |

**Verdict.** The draft survives the unit-tests / service-tests / overview decisions intact. The folder structure is already aligned. Five small clarifications close the remaining gaps; an optional trim brings tone in line with the tighter sibling docs. No restructure needed.
