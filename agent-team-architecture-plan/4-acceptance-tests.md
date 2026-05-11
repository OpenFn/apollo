# Section 4 — Acceptance Tests Architecture

> Scope: quality-, voice-, and style-focused evaluation of Apollo chat services (`global_chat`, `workflow_chat`, `job_chat`) against product-owner-authored hero questions. Judged by an LLM-as-judge, reviewable by a human (Joe or Brandon), optionally logged to Langfuse for trend analysis.

**Non-goals (other tiers):**

- Unit tests of pure functions → Section 1.
- Mocked-LLM `main()` invocations → Section 2.
- Functional flow with regex content assertions → Section 3.

Acceptance answers a different question than integration: not "does the system function end-to-end?" but "does the answer sound like us, read well, satisfy the user's intent, and not regress in voice as we bump model versions?"

This section is written against the unit-test architecture that landed in #486 (commit `e249b86`) — those folder names, that `conftest.py`, that `services/testing/` package. Where the older draft of this section disagreed with what shipped, the shipped reality wins.

---

## 1. Guiding principles

1. **Specs are markdown.** A PO edits a text file, not Python. YAML frontmatter + markdown sections.
2. **HTTP is internal plumbing.** Specs never mention ports, payload shapes, or service internals.
3. **Live models.** The whole point is to audit the real production path after model upgrades.
4. **LLM-as-judge with receipts.** Every evaluation records the judge's reasoning so a human can spot-check.
5. **pytest is the runner.** Same as every other tier. Spec files are collected via a tiny `pytest_collect_file` hook. No custom CLI, no `bless`/`differ`/`migrate-questions` subcommands.
6. **Human-triggered only.** Never on every push, never on a schedule. Humans decide when a change is big enough to warrant an acceptance run — via PR label or manual `workflow_dispatch`.
7. **No `test_hooks`.** Acceptance dispatches over real HTTP through the running bun server; the bridge strips anything beyond the JSON payload, so the service-tier `test_hooks` second arg is invisible here. Every call hits the production code path with real LLM responses.

---

## 2. Directory layout

Acceptance specs live alongside the service they test, in an `acceptance/` subfolder of `services/<svc>/tests/`. This is consistent with the unit-tests merge — tier directories (`unit/`, `integration/`, and now `acceptance/`) sit flat under `services/<svc>/tests/` with no top-level `tests/` tree.

```
services/<svc>/tests/
  acceptance/
    *.md                          # one spec per file
    _template.md                  # copy-paste starter (underscore = skipped by collector)
```

Concretely:

```
services/global_chat/tests/acceptance/
  hero-patient-sync.md
  voice-concise-answers.md
  refuse-non-openfn-questions.md
services/workflow_chat/tests/acceptance/
  *.md
services/job_chat/tests/acceptance/
  *.md
```

**Cross-service specs** (refusals, safety, "hero" questions that exercise the orchestrator end-to-end) live under `services/global_chat/tests/acceptance/` since `global_chat` is the entry point everyone hits.

**Tool services** (e.g. `services/tools/search_documentation/`) inherit the same pattern — if a tool ever needs its own acceptance specs, drop them in `services/tools/<tool>/tests/acceptance/`. The shared collector picks them up with no additional config. In practice tools are judged through the chat services that call them; standalone tool acceptance specs are unlikely on day one.

The judge helper and the markdown-spec pytest collector live in the **shared `services/testing/` package**:

```
services/testing/
  __init__.py                     # already shipped
  README.md                       # already shipped
  yaml_assertions.py              # already shipped
  judge.py                        # new — LLM-as-judge helper (~150 lines)
  spec_collector.py               # new — SpecFile / SpecItem / parse_spec
```

`services/testing/` is on the import path via `pyproject.toml`'s `pythonpath = ["services"]`, so `from testing.judge import evaluate` works without path-munging. (The older draft of this section talked about an `apollo/testing/` peer of `services/` — that never shipped. The actual location is `services/testing/`.)

The `pytest_collect_file` hook is wired into the **root `conftest.py`** (at the repo root — that's where the unit-tests merge put the tier auto-marker) so it discovers `*.md` under any `acceptance/` folder anywhere in `services/`.

**No `golden/` tree, no `reports/` folder in git.** Langfuse is the trend / comparison backend. Local test output (pass/fail + judge reasoning) comes from pytest stdout and `--junitxml`. If a run needs an HTML report, generate it with `pytest-html` when someone asks for it — not preemptively.

**No `services/llm_evaluator/` service.** The judge is a helper module that calls Anthropic directly via the SDK. Promote to a service only when a non-test caller needs to invoke it.

---

## 3. Spec format

One spec per markdown file. YAML frontmatter + named markdown sections.

### 3.1 Frontmatter

```yaml
---
id: global-chat.hero.patient-sync
title: "Build a CommCare to DHIS2 sync"
service: global_chat                     # global_chat | workflow_chat | job_chat
tags: [hero, voice, multi-turn]
runs: 3                                  # default 1 — number of times to run the same spec
judge_model: claude-sonnet-4-6           # defaults to the same in the root conftest
---
```

Only `id` and `service` are required. Everything else inherits sensible defaults from the root `conftest.py`.

### 3.2 Body sections (top-level markdown headers, case-insensitive)

| Section | Required | Purpose |
|---|---|---|
| `# conversation` | one of conversation/question | `- user:` / `- assistant:` list. Last user line is tested; earlier lines become `history`. |
| `# question` | one of conversation/question | Shorthand for a single-turn conversation. |
| `# context` | optional | YAML block merged into payload: `workflow_yaml`, `page`, `context`, `attachments`, etc. |
| `# must_include` | optional | Substrings or `/regex/` that must appear in `response`. Deterministic; failure short-circuits before the judge runs. |
| `# must_not_include` | optional | Opposite. |
| `# assertions` | required | Natural-language criteria, one per bullet — each passed to the LLM judge. |
| `# notes` | optional | Reviewer context, not sent to the judge. |

### 3.3 Example

```markdown
---
id: global-chat.hero.patient-sync
title: "Build a CommCare to DHIS2 sync"
service: global_chat
tags: [hero, planner]
runs: 3
---

# conversation

- user: "I want to create a workflow that fetches new patient registrations from CommCare every hour and creates matching tracked entities in DHIS2."

# must_include
- /commcare/i
- /dhis2/i

# must_not_include
- "I cannot help with that"

# assertions
- The response proposes a workflow with at least two jobs.
- The tone is warm and collaborative, not clinical.
- An attached workflow_yaml is present and syntactically valid.
- The response does not leak the user's api_key or any secret-looking string.
```

---

## 4. Collection: spec → pytest item

The root `conftest.py` already auto-applies a tier marker by walking `item.path.parts` for the tier directory name (see `_TIER_DIRS = ("unit", "service", "integration", "acceptance")` in the shipped file). That mechanism works for any pytest item whose path lives under an `acceptance/` folder — including `SpecItem`s collected from markdown — so **no extra marker plumbing is needed**. Acceptance specs become `pytest -m acceptance`-selectable for free.

The collector itself is a standard `pytest_collect_file` hook in the root `conftest.py`:

```python
def pytest_collect_file(parent, file_path):
    if (
        file_path.suffix == ".md"
        and not file_path.name.startswith("_")
        and file_path.parent.name == "acceptance"
    ):
        return SpecFile.from_parent(parent, path=file_path)

class SpecFile(pytest.File):
    def collect(self):
        spec = parse_spec(self.path)
        for run_index in range(spec.runs):
            yield SpecItem.from_parent(
                self,
                name=f"{spec.id}[run={run_index}]",
                spec=spec,
                run_index=run_index,
            )

class SpecItem(pytest.Item):
    def runtest(self):
        payload = build_payload(self.spec, self.run_index)
        response = self.client.call(self.spec.service, payload)
        check_must_include(self.spec, response)       # hard precondition; raises on fail
        verdict = judge.evaluate(self.spec, response, model=self.spec.judge_model)
        if not verdict.passed:
            raise AssertionError(verdict.summary)
```

`SpecFile`, `SpecItem`, and `parse_spec` live in `services/testing/spec_collector.py`; the hook in `conftest.py` is a four-line import + dispatch.

Each run is a separate pytest item. Benefits: `pytest -m acceptance` works, `--junitxml` works, `pytest-xdist` works, filtering with `-k hero` works. No new runner.

A tiny `pytest_sessionfinish` hook counts, per spec, how many of the N runs the judge marked `passed=True` and prints `spec-id: 2/3 passed` to stdout. No pass/fail policy is applied — the count is raw output for humans to read. (The pytest exit code still reflects individual item pass/fail in the usual way.)

**Sequencing note.** The collector hook is small enough to land in the scaffolding PR (overview §9 step 1) alongside the existing root `conftest.py` work. The first acceptance *spec* doesn't ship until later, but having the collector in place from day one means adding `acceptance/*.md` is purely additive.

---

## 5. The judge

`services/testing/judge.py` is a single module (~150 lines). Not an Apollo service.

### 5.1 Interface

```python
@dataclass
class Verdict:
    passed: bool
    score: float                        # 0..1 — fraction of criteria passed
    criteria: list[CriterionResult]
    reasoning_summary: str              # shown on pytest failure
    judge_usage: dict                   # input/output tokens

@dataclass
class CriterionResult:
    criterion: str
    passed: bool
    reasoning: str
    evidence: str                       # verbatim span from candidate

def evaluate(spec: Spec, response: dict, *, model: str) -> Verdict: ...
```

### 5.2 Prompt strategy

Judge prompt forces JSON via prefilled `{` and demands per-criterion verdict + verbatim evidence; bad JSON or refusal → `Verdict(passed=False, reasoning_summary="judge_error: ...")` surfaced loudly. Full prompt text lives in the judge module's docstring; this section deliberately doesn't repeat it.

### 5.3 Why a helper and not a service

The judge only has one caller today (this tier). A whole Apollo service + `/services/llm_evaluator` HTTP endpoint + per-service test directory is overkill for that. If future callers appear (a ranker for `search_docsite`, a sanity-check step in a generator), promote `services/testing/judge.py` to `services/llm_evaluator/llm_evaluator.py` — it's a ~50-line reshape, not a redesign.

### 5.4 Self-tests for the judge

The judge module itself needs tests. Per the unit-tier I/O policy (root `conftest.py` blocks `anthropic.Anthropic.__init__` for any test marked `unit`), the parts of the judge that touch a mocked Anthropic transport are **service-tier**, not unit-tier:

- **Unit.** Pure helpers: prompt builder, JSON parser, frontmatter parser, `_format_criteria()`. No Anthropic construction. Lives at `services/testing/tests/unit/test_judge_*.py` (or wherever testing-package tests end up — see below).
- **Service.** End-to-end `evaluate()` against a `MockAnthropic` transport. Lives at `services/testing/tests/service/test_judge_evaluate.py`.

Open detail to settle when the service tier lands: tests for code in `services/testing/` could live alongside the module (`services/testing/tests/`) or under a shared `services/tests/` umbrella (the precedent the unit-tests doc set for `services/util.py` helpers). Either works; just commit to one before the judge ships.

---

## 6. Langfuse integration

Langfuse is already wired on `add-langfuse` — acceptance leans on it lightly for cross-run comparison. The runner does NOT rebuild Langfuse's dataset / score UI.

### 6.1 Already in place (we reuse)

- `services/langfuse_util.py::should_track()` gates trace export. Payloads set `user.employee=True` to stay inside the employee window.
- `@observe` on each chat service's `main()` — every acceptance run is automatically traced when `LANGFUSE_TRACING=true`.

### 6.2 What we add

1. **Session tagging.** Each run sets `session_id = f"acceptance-{spec.id}-run{i}"` and `tags = ["acceptance", spec.id, ...spec.tags]`. Done via Langfuse's `propagate_attributes`.
2. **Score push.** After the judge returns, write one score per run: `acceptance_pass` (0/1) and `acceptance_score` (0..1). Use Langfuse's Scores API directly from `services/testing/judge.py` — no `langfuse_sink.py` wrapper.
3. **Cross-version comparison.** Native Langfuse dataset-runs view does this. The collector surfaces the URL in stdout.

### 6.3 What we don't do via Langfuse

- No Langfuse-hosted eval (we own the prompt).
- No hard dependency — acceptance runs offline if `LANGFUSE_PUBLIC_KEY` is unset OR `LANGFUSE_TRACING=false`; scores are skipped, runs still complete.

---

## 7. Multi-run sampling

Specs declare `runs: N` in frontmatter; default is `1`. Each of the N runs becomes a separate pytest item, named `<spec-id>[run=0]` ... `<spec-id>[run=N-1]`, judged independently. `pytest_sessionfinish` prints `<spec-id>: <k>/<N> passed` to stdout. The pytest exit code reflects individual item pass/fail; the count is raw output for humans to read — no `2-of-3` policy, no aggregator. Whoever reads the output decides whether the ratio is acceptable for that spec.

Per-run pass/fail comes from the LLM judge (`Verdict.passed`, §5.1).

---

## 8. Human review loop

**Primary: Langfuse UI.** Joe / Brandon open the dashboard, filter by `tags:acceptance`, review candidate + judge reasoning + score, override with a human annotation if they disagree.

**Secondary: pytest stdout / JUnit.** CI logs show `FAIL global-chat.hero.patient-sync[run=1]` with the judge's reasoning summary as the pytest message. Enough for a quick triage.

No dedicated HTML report on day one. Add `pytest-html` the first time someone asks for it.

---

## 9. Triggers

Acceptance is **never triggered automatically**. A human decides when a change is big enough to warrant spending the money on a run.

| Trigger | Mechanism |
|---|---|
| Local manual | `poetry run pytest -m acceptance` |
| CI manual (any branch) | GH Actions `workflow_dispatch` on the acceptance workflow |
| PR label | Apply `run-acceptance` label to a PR |

Explicitly excluded: no cron, no nightly, no push-to-main, no tag-push, no scheduled runs of any kind. If the team later decides they want continuous drift monitoring, that's a deliberate policy change — not a default.

---

## 10. CI workflow

A second GH Actions workflow alongside the shipped `unit-tests.yaml`. Two reasonable shapes; pick one when the integration tier's workflow lands so the choice is consistent:

- **Option A — shared `llm-tests.yaml`.** One file with two jobs (`integration` and `acceptance`), each gated by its own label / `workflow_dispatch` condition. Matches the original overview §6 design. Cleaner if integration and acceptance share env wiring.
- **Option B — dedicated `acceptance-tests.yaml`.** Mirrors the existing `unit-tests.yaml` naming (one file per tier). Easier to grep, easier to point a human at "the acceptance workflow."

Either way, the acceptance job's shape mirrors the integration job (see `3-integration-tests.md` §9) with three differences:

1. **Triggers:** `run-acceptance` label or `workflow_dispatch` only — no `push`, no `schedule`.
2. **Env:** `LANGFUSE_TRACING=true` (acceptance runs always trace; that's the point) plus the standard `*_TEST` secrets.
3. **Timeout:** 45 minutes as a hard ceiling.

The run command is `poetry run pytest -m acceptance -v --junitxml=tmp/test-logs/acceptance-junit.xml`. Note this is marker-filtered, not path-filtered like `unit-tests.yaml` (`pytest services/*/tests/unit`) — markdown specs need the collector hook to fire, which means crawling the test tree, which means filtering by marker. Deliberate divergence from the unit pattern, not an oversight.

JUnit XML uploads as an artifact for 14 days.

---

## 11. Cost control

Day-one approach is human-gated triggering + sensible defaults, not elaborate budget code:

- Never automatic — every run is a deliberate human action.
- `runs: 1` default — specs must opt into sampling.
- Judge defaults to `claude-sonnet-4-6` (not opus).
- Prompt caching on candidate calls — preserved across the N runs of one spec by shared `session_id`.
- 45-minute workflow timeout as a hard ceiling.

A budget env + soft circuit breaker can be added the first time a manual run surprises someone. Not on day one.

---

## 12. Dependencies on the integration tier

Acceptance and integration both dispatch through a live bun server, so they share infrastructure that the integration tier owns:

- `services/testing/server.py` — session-scoped `apollo_server` fixture (spawn bun, poll `GET /` until ready, SIGTERM on teardown, honour `APOLLO_TEST_BASE_URL` to reuse a running staging server).
- `services/testing/server.py::ApolloClient` — wraps `.call()`, `.stream()`, `.ws()`. The collector's `SpecItem.runtest` uses `.call()`.

Neither exists today. Acceptance can't ship before integration's server fixture lands. The collector hook itself can ship earlier (scaffolding PR) — markdown specs would just have no runner attached until `ApolloClient` arrives.

---

## 13. Extensibility

Adding a new sub-agent or tool — no Python required:

1. Ensure the new service exposes `main()` at `services/<name>/<name>.py` (auto-mounts via `describe-modules.ts`).
2. Create `services/<name>/tests/acceptance/` and drop markdown specs.

Adding a new judge model: list it in the root `conftest.py` (or let it be free-form — strings all the way). `judge_model:` in frontmatter.

---

## 14. Relationship to integration

| Concern | Integration | Acceptance |
|---|---|---|
| Goal | Functional correctness | Quality, voice, style |
| Assertions | Regex + shape | Natural-language criteria + LLM judge |
| Trigger | PR label / push to main / manual | PR label / manual — **never automatic** |
| Stability | Deterministic | Probabilistic (N runs) |
| Runner | pytest | pytest |
| Marker | `@pytest.mark.integration` (auto-applied by root conftest) | `@pytest.mark.acceptance` (auto-applied by root conftest) |
| Location | `services/<svc>/tests/integration/test_*.py` | `services/<svc>/tests/acceptance/*.md` |
| `test_hooks` | not used (real HTTP) | not used (real HTTP) |

**Overlap rule:** a test lives in exactly one tier. An "acceptance" spec that merely asserts a YAML attachment exists belongs in integration. An integration test that checks "the tone feels terse enough" belongs in acceptance.

---

## 15. Migration of existing artefacts

- `services/job_chat/evaluation/questions.md` — mostly-compatible format. One-time manual conversion (split per entry, add frontmatter, drop into `services/job_chat/tests/acceptance/`). No migration CLI needed — it's a one-shot editor task.
- `services/global_chat/tests/test_workflow_chat_qualitative.py`, `services/global_chat/tests/test_job_chat_qualitative.py`, `services/workflow_chat/tests/test_qualitative.py`, `services/job_chat/tests/test_qualitative.py` — the prose at the top of each test (in `print()` statements) becomes `# notes`; `content`/`context` become spec sections; qualitative asserts become `# assertions` bullets. Drop the resulting markdown files into the relevant service's `acceptance/` folder (use `services/global_chat/tests/acceptance/` for cross-service tests targeting the orchestrator). Any machine-checkable asserts move to integration.
- `temp_test_empty_response_guard.py` (recently added in #487 to all three chat services) — these are service-tier candidates (mocked LLM, structural assertion), not acceptance. Flagged here so they don't accidentally end up in `acceptance/` during migration.

Migration is opt-in, one file at a time.

---

## 16. What this tier deliberately does NOT do

- **No top-level `tests/` tree.** Specs live under their service.
- **No `apollo/testing/` peer of `services/`.** The shared package is `services/testing/` — that's what shipped in #486.
- **No `services/llm_evaluator/` service.** Judge is a helper module.
- **No custom acceptance runner.** Pytest collects specs; that's it.
- **No `bless` / `differ` / `migrate-questions` / `review` subcommands.** The first two make sense if we adopt golden-file diffing; we don't on day one (Langfuse's dataset-runs comparison is the primitive). The last two are one-off editor tasks.
- **No `golden/` git tree.** Model drift is tracked in Langfuse.
- **No HTML reporter.** `pytest-html` is a line in `pyproject.toml` the day we want it.
- **No per-spec cost caps, budget estimator, `list`/`lint` commands, skip-on-no-change mode.** Defer until bills say otherwise.
- **No `criteria_mode: weighted` with per-criterion weights.** `all` or `any` across criteria. Add weighting when a spec genuinely needs it.

---

## Summary

Acceptance = markdown specs in `services/<svc>/tests/acceptance/` + a `pytest_collect_file` hook in the existing root `conftest.py` + a tiny judge helper in `services/testing/judge.py` + Langfuse scores. The `acceptance` marker is already declared in `pyproject.toml` and auto-applied by the existing path-based hook — no new marker plumbing. No new Apollo service, no custom runner, no golden tree, no top-level `tests/` directory. Runs via the standard pytest mechanism under a label-gated GH Actions workflow. Adding a sub-agent or tool means dropping markdown files under that service's `acceptance/` folder. The judge promotes to a service the day it has a second caller; nothing else changes. Acceptance depends on the integration tier shipping `services/testing/server.py` (`apollo_server` fixture + `ApolloClient`) — it can't run before that lands, though the collector itself can ship earlier in the scaffolding PR.
