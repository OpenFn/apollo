# Section 4 — Acceptance Tests Architecture (Simplified)

**Scope:** quality-, voice-, and style-focused evaluation of Apollo chat services (`global_chat`, `workflow_chat`, `job_chat`) against product-owner-authored hero questions. Judged by an LLM-as-judge, reviewable by a human (Joe or Brandon), optionally logged to Langfuse for trend analysis.

**Non-goals (other tiers):**

- Unit tests of pure functions → Section 1.
- Mocked-LLM `main()` invocations → Section 2.
- Functional flow with regex content assertions → Section 3.

Acceptance answers a different question: not "does the system function end-to-end?" but "does the answer sound like us, read well, satisfy the user's intent, and not regress in voice as we bump model versions?"

---

## 1. Guiding principles

1. **Specs are markdown.** A PO edits a text file, not Python. YAML frontmatter + markdown sections.
2. **HTTP is internal plumbing.** Specs never mention ports, payload shapes, or service internals.
3. **Live models.** The whole point is to audit the real production path after model upgrades.
4. **LLM-as-judge with receipts.** Every evaluation records the judge's reasoning so a human can spot-check.
5. **pytest is the runner.** Same as every other tier. Spec files are collected via a tiny `pytest_collect_file` hook. No custom CLI, no `bless`/`differ`/`migrate-questions` subcommands.
6. **Human-triggered only.** Never on every push, never on a schedule. Humans decide when a change is big enough to warrant an acceptance run — via PR label or manual `workflow_dispatch`.

---

## 2. Directory layout

```
tests/
├── conftest.py                       # apollo_server + ApolloClient (owned by integration tier; shared)
├── integration/                      # Section 3
└── acceptance/                       # THIS TIER
    ├── conftest.py                   # pytest_collect_file hook; auto-applies @pytest.mark.acceptance; judge fixture
    ├── judge.py                      # small LLM-as-judge helper (~150 lines)
    ├── specs/
    │   ├── _template.md
    │   ├── global_chat/
    │   │   ├── hero-patient-sync.md
    │   │   └── voice-concise-answers.md
    │   ├── workflow_chat/
    │   │   └── *.md
    │   ├── job_chat/
    │   │   └── *.md
    │   └── shared/
    │       └── refuse-non-openfn-questions.md
    └── fixtures/                     # sample workflow YAMLs, job code, etc.
```

**No `golden/` tree, no `reports/` folder in git.** Langfuse is the trend / comparison backend. Local test output (pass/fail + judge reasoning) comes from pytest stdout and `--junitxml`. If a run needs an HTML report, generate it from pytest with `pytest-html` when someone asks for it — not preemptively.

**No `services/llm_evaluator/` service.** The judge is a helper module in `tests/acceptance/judge.py` that calls Anthropic directly via the SDK. Promote to a service only when a non-test caller needs to invoke it.

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
judge_model: claude-sonnet-4-6           # defaults to the same in conftest
---
```

Only `id` and `service` are required. Everything else inherits sensible defaults from `tests/acceptance/conftest.py`.

### 3.2 Body sections (top-level markdown headers, case-insensitive)

| Section | Required | Purpose |
|---|---|---|
| `# conversation` | one of conversation/question | `- user:` / `- assistant:` list. Last user line is tested; earlier lines become `history`. |
| `# question` | one of conversation/question | Shorthand for a single-turn conversation. |
| `# context` | optional | YAML block merged into payload: `workflow_yaml`, `page`, `context`, `attachments`, etc. |
| `# must_include` | optional | Substrings or `/regex/` that must appear in `response`. Deterministic; failure short-circuits before judge runs. |
| `# must_not_include` | optional | Opposite. |
| `# assertions` | required | Natural-language criteria, one per bullet — each passed to the LLM judge. |
| `# notes` | optional | Reviewer context, not sent to judge. |

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

`tests/acceptance/conftest.py` implements a standard pytest collection hook:

```python
def pytest_collect_file(parent, file_path):
    if file_path.suffix == ".md" and not file_path.name.startswith("_"):
        return SpecFile.from_parent(parent, path=file_path)

class SpecFile(pytest.File):
    def collect(self):
        spec = parse_spec(self.path)
        for run_index in range(spec.runs):
            yield SpecItem.from_parent(
                self, name=f"{spec.id}[run={run_index}]",
                spec=spec, run_index=run_index,
            )

class SpecItem(pytest.Item):
    def runtest(self):
        payload = build_payload(self.spec, self.run_index)
        response = self.client.call(self.spec.service, payload)
        check_must_include(self.spec, response)   # hard precondition; raises on fail
        verdict = judge.evaluate(self.spec, response, model=self.spec.judge_model)
        if not verdict.passed:
            raise AssertionError(verdict.summary)
```

Each run is a separate pytest item. Benefits: `pytest -m acceptance` works, `--junitxml` works, `pytest-xdist` works, filtering with `-k hero` works. No new runner.

A tiny `pytest_sessionfinish` hook counts, per spec, how many of the N runs the judge marked `passed=True` and prints `spec-id: 2/3 passed` to stdout. No pass/fail policy is applied — the count is raw output for humans to read. (The pytest exit code still reflects individual item pass/fail in the usual way.)

---

## 5. The judge

`tests/acceptance/judge.py` is a single module (~150 lines). Not an Apollo service.

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

- System prompt instructs the judge to be strict and to quote evidence verbatim.
- User prompt: numbered criteria + candidate response (+ attachments if present) + demand for JSON output with per-criterion pass/fail + reasoning.
- Prefilled `{` to force JSON.
- Malformed JSON / judge refusal → verdict with `passed=False`, reason `judge_error`. Surfaced loudly.

### 5.3 Why a helper and not a service

The judge only has one caller today (acceptance tier). A whole Apollo service + `/services/llm_evaluator` HTTP endpoint + per-service test directory is overkill for that. If future callers appear (a ranker for search_docsite, a sanity-check step in gen_job), promote `judge.py` to `services/llm_evaluator/llm_evaluator.py` — it's a ~50-line reshape, not a redesign.

### 5.4 Self-tests

`tests/acceptance/test_judge_unit.py` exercises the prompt builder and JSON parser with canned inputs. Uses `MockAnthropicClient` from the service tier's shared helpers.

---

## 6. Langfuse integration

Langfuse is already wired on `add-langfuse` — acceptance leans on it lightly for cross-run comparison. The runner does NOT rebuild Langfuse's dataset / score UI.

### 6.1 Already in place (we reuse)

- `services/langfuse_util.py::should_track()` gates trace export. Payloads set `user.employee=True` to stay inside the employee window.
- `@observe` on each chat service's `main()` — every acceptance run is automatically traced.

### 6.2 What we add

1. **Session tagging.** Each run sets `session_id = f"acceptance-{spec.id}-run{i}"` and `tags = ["acceptance", spec.id, ...spec.tags]`. Done via Langfuse's `propagate_attributes`.
2. **Score push.** After the judge returns, write one score per run: `acceptance_pass` (0/1) and `acceptance_score` (0..1). Use Langfuse's Scores API directly from `judge.py` — no `langfuse_sink.py` wrapper.
3. **Cross-version comparison.** Native Langfuse dataset-runs view does this. Runner surfaces the URL in stdout.

### 6.3 What we don't do via Langfuse

- No Langfuse-hosted eval (we own the prompt).
- No hard dependency — acceptance runs offline if `LANGFUSE_PUBLIC_KEY` is unset; scores are just skipped.

---

## 7. Multi-run sampling

Specs that benefit from sampling (tone, voice, any criterion where the LLM varies between runs) declare `runs: N` in the frontmatter. Default is `1`.

Mechanics:

- The collection hook yields N separate pytest items per spec, named `<spec-id>[run=0]` ... `<spec-id>[run=N-1]`.
- Each run calls the service independently and is judged independently by `tests/acceptance/judge.py`.
- A `pytest_sessionfinish` hook tallies per spec: `<spec-id>: <passed>/<total> passed` to stdout.

That's it — no `all` / `majority` / `any` policies, no named aggregator, no default that says "2 out of 3 is good enough." Whoever reads the output decides whether the ratio is acceptable for that spec. A refusal spec with 2/3 is probably a regression; a voice spec with 2/3 might be fine. Humans make the call, the tooling just reports the count.

Per-run pass/fail comes from the LLM judge (`Verdict.passed`, see §5.1). The count in `2/3 passed` is simply the number of runs whose judge verdict was `passed=True`.

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
| Local manual | `poetry run pytest tests/acceptance -m acceptance` |
| CI manual (any branch) | GH Actions `workflow_dispatch` on `llm-tests.yaml` |
| PR label | Apply `run-acceptance` label to a PR |

Explicitly excluded: no cron, no nightly, no push-to-main, no tag-push, no scheduled runs of any kind. If the team later decides they want continuous drift monitoring, that's a deliberate policy change — not a default.

Shares `.github/workflows/llm-tests.yaml` with the integration tier — see Section 3 §9 for the skeleton. Acceptance is a second job in the same workflow, gated by its own label condition.

---

## 10. CI workflow (acceptance job)

Appended to `.github/workflows/llm-tests.yaml`:

```yaml
  acceptance:
    # Human-triggered only. No 'schedule' trigger — by design.
    if: >-
      (github.event_name == 'pull_request' && github.event.label.name == 'run-acceptance')
      || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 45
    env:
      CI: "true"
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY_TEST }}
      OPENAI_API_KEY:    ${{ secrets.OPENAI_API_KEY_TEST }}
      LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY_TEST }}
      LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY_TEST }}
      LANGFUSE_BASE_URL:   ${{ secrets.LANGFUSE_BASE_URL }}
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - uses: snok/install-poetry@v1
      - run: bun install
      - run: poetry install --with test-integration
      - run: poetry run pytest tests/acceptance -v -m acceptance --junitxml=tests/acceptance/junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: acceptance-junit-${{ github.run_id }}
          path: tests/acceptance/junit.xml
          retention-days: 14
```

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

## 12. Extensibility

Adding a new sub-agent or tool — no Python required:

1. Ensure the new service exposes `main()` at `services/<name>/<name>.py` (auto-mounts).
2. Create `tests/acceptance/specs/<name>/` and drop markdown specs.

Adding a new judge model: add to the allowed set in `tests/acceptance/conftest.py` (or let it be free-form — strings all the way). `judge_model:` in frontmatter.

---

## 13. Relationship to integration

| Concern | Integration | Acceptance |
|---|---|---|
| Goal | Functional correctness | Quality, voice, style |
| Assertions | Regex + shape | Natural-language criteria + LLM judge |
| Trigger | PR label / push to main / manual | PR label / manual — **never automatic** |
| Stability | Deterministic | Probabilistic (N runs) |
| Runner | pytest | pytest |
| Marker | `@pytest.mark.integration` | `@pytest.mark.acceptance` |

**Overlap rule:** a test lives in exactly one tier. An "acceptance" spec that merely asserts a YAML attachment exists belongs in integration. An integration test that checks "the tone feels terse enough" belongs in acceptance.

---

## 14. Migration of existing artefacts

- `services/job_chat/evaluation/questions.md` — mostly-compatible format. One-time manual conversion (split per entry, add frontmatter). No migration CLI needed — it's a one-shot editor task.
- `services/global_chat/tests/test_*_qualitative.py` — the prose at the top of each test (in `print()` statements) becomes `# notes`; `content`/`context` become spec sections; qualitative asserts become `# assertions` bullets; any machine-checkable asserts move to integration.
- Migration is opt-in, one file at a time.

---

## 15. What this tier deliberately does NOT do

- **No `services/llm_evaluator/` service.** Judge is a helper module.
- **No custom acceptance runner.** Pytest collects specs; that's it.
- **No `bless` / `differ` / `migrate-questions` / `review` subcommands.** The first two make sense if we adopt golden-file diffing; we don't on day one (Langfuse's dataset-runs comparison is the primitive). The last two are one-off editor tasks.
- **No `golden/` git tree.** Model drift is tracked in Langfuse.
- **No HTML reporter.** `pytest-html` is a line in `pyproject.toml` the day we want it.
- **No per-spec cost caps, budget estimator, `list`/`lint` commands, skip-on-no-change mode.** Defer until bills say otherwise.
- **No `criteria_mode: weighted` with per-criterion weights.** `all` or `any` across criteria. Add weighting when a spec genuinely needs it.

---

## Summary

Acceptance = markdown specs + pytest collector + tiny judge helper + Langfuse scores. No new Apollo service, no custom runner, no golden tree. Runs via the standard pytest mechanism under a shared `llm-tests.yaml` workflow. Adding a sub-agent means dropping markdown files under `tests/acceptance/specs/<name>/`. The judge promotes to a service the day it has a second caller; nothing else changes.
