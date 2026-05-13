# Section 4 — Acceptance Tests Architecture

> Scope: quality-, voice-, and style-focused evaluation of Apollo chat services (`global_chat`, `workflow_chat`, `job_chat`) against hero questions. Each test combines deterministic structural assertions (that already exist today) with an LLM judge that evaluates a small list of natural-language criteria.

**Non-goals (other tiers):**

- Unit tests of pure functions → Section 1.
- Mocked-LLM `main()` invocations → Section 2.
- Functional flow with regex content assertions → Section 3.

Acceptance answers a different question than integration: not "does the system function end-to-end?" but "does the answer sound like us, read well, satisfy the user's intent, and not regress in voice as we bump model versions?" — but **on top of** all the structural checks the team already trusts.

This section is written against the unit-test architecture that landed in #486 — those folder names, that `conftest.py`, that `services/testing/` package. It is also written against what the existing `test_qualitative.py` (in `workflow_chat` and `job_chat`) and `test_planner_multistep.py` (in `global_chat`) actually need to express, because those tests are the migration target.

---

## 1. Guiding principles

1. **Tests are Python.** Same shape as the existing `test_qualitative.py` files — full control over the rich, service-specific payload (`existing_yaml`, `expression`, `adaptor`, `page_name`, `meta.last_page`, `meta.rag`, `suggest_code`, `errors`, …). No custom DSL to learn.
2. **Two assertion layers per test.**
   - **Structural** — deterministic Python asserts: yaml-shape helpers, `[pg:…]` prefix checks, attachment shape, tool-call sequencing, "response must not contain 'yaml'", etc. These are what the existing qualitative tests already do, and they stay exactly as they are.
   - **Quality** — one `judge.evaluate(...)` call near the end of the test. Takes a small list of natural-language criteria; returns a verdict the test asserts on.
3. **The criteria field is obvious.** Each test has a clearly named module-level constant — `QUALITY_CRITERIA` — that anyone, technical or not, can read and edit without touching the rest of the test. Adding a new criterion is a one-line edit. The constant is fed verbatim into the judge prompt.
4. **The judge flags more than just the listed criteria.** The judge prompt instructs the model to:
   1. Verdict each listed criterion (pass/fail + verbatim evidence).
   2. *Also* flag anything else notable about the response — tone drift, hedging, hallucinated facts, leaked secrets, anything that looks off — even if no criterion covers it. These show up in the verdict as `general_flags`.
   This means a criteria list never has to be exhaustive — POs write what they care about most, the judge surfaces surprises.
5. **Payload building uses intuitive names.** A builder like `build_job_chat_payload(...)` exposes named kwargs that map to user-facing concepts: `current_job_code`, `current_adaptor`, `current_page`, `previous_page`, `rag_results`, `suggest_code`. The builder translates to the underlying JSON keys. Lowers the barrier for anyone not steeped in the payload spec.
6. **Live HTTP, live models.** Specs dispatch through the running bun server via `ApolloClient` (from the integration tier). Same path a user hits in production. No mocks. No `test_hooks` — that's service-tier only.
7. **Run on demand only.** Never in an automated pipeline. Humans decide when a change is big enough to warrant a run — typically before a release, after a prompt/model bump, or when investigating a quality regression.
8. **pytest is the runner.** Tier-marker auto-applied by the existing path-based hook in root `conftest.py` (folder name `acceptance` → `pytest.mark.acceptance`). No custom collector.

---

## 2. Directory layout

Acceptance tests are Python files in an `acceptance/` subfolder of `services/<svc>/tests/`. Consistent with the unit-tests merge (tier directories sit flat under `services/<svc>/tests/`).

```
services/global_chat/tests/acceptance/
  __init__.py
  test_planner_multistep.py             # migrated from tests/test_planner_multistep.py
  test_planner_underspecified.py        # vague-request specs from same file
  test_routing_voice.py                 # cross-service voice / refusal specs
services/workflow_chat/tests/acceptance/
  __init__.py
  test_first_turn.py                    # migrated from test_qualitative.py
  test_conversational_turn.py
  test_long_yaml.py
  test_navigation_job_to_workflow.py
services/job_chat/tests/acceptance/
  __init__.py
  test_basic_input.py
  test_contextualised_input.py
  test_adaptor_context_switching.py
  test_navigation_workflow_to_job.py
```

**Cross-service specs** (planner orchestration, refusals, safety) live under `services/global_chat/tests/acceptance/` since `global_chat` is the entry point.

**Tool services** (e.g. `services/tools/search_documentation/`) inherit the same pattern — if a tool ever needs its own acceptance tests, drop them in `services/tools/<tool>/tests/acceptance/`. The existing path-based marker hook picks them up with no config. In practice tools are judged through the chat services that call them.

The judge, payload builders, response helpers, and migrated yaml-assertions all live in the **shared `services/testing/` package**:

```
services/testing/
  __init__.py                     # already shipped
  README.md                       # already shipped
  yaml_assertions.py              # already shipped — kept as-is
  judge.py                        # new — LLM-as-judge helper (§5)
  payloads.py                     # new — build_*_chat_payload() builders (§7)
  responses.py                    # new — get_attachment, assert_routed_to, assert_agent_calls (§7)
  apollo_client.py                # new — owned by integration tier; reused here
```

(`apollo_client.py` and the `apollo_server` session fixture are integration-tier deliverables. Acceptance is a strict consumer — it can't run before they land. See §13.)

**No `golden/` tree, no `reports/` folder in git.** Langfuse is the trend / comparison backend. Local output is pytest stdout + `--junitxml`. Add `pytest-html` the day someone asks.

**No `services/llm_evaluator/` service.** Judge is a helper module. Promote to a service the day a non-test caller appears.

---

## 3. What an acceptance test looks like

A single self-contained file. Roughly the same shape as today's `test_qualitative.py` entries, with three deliberate additions:

1. A module-level `QUALITY_CRITERIA` constant (the "edit me" surface for POs).
2. A payload built via `build_<svc>_chat_payload(...)` with intuitive named kwargs instead of nested dicts.
3. A `judge.evaluate(...)` call at the end alongside the existing structural asserts.

### 3.1 Example: workflow_chat navigation test

(Migration target: `services/workflow_chat/tests/test_qualitative.py::test_navigation_job_to_workflow`)

```python
"""User just navigated from a job-code page to a workflow editor and asks for
a new step. The model should infer the context switch and respond about the
workflow, not the job code's error handling."""

import yaml

from testing import judge
from testing.apollo_client import ApolloClient
from testing.payloads import build_workflow_chat_payload
from testing.yaml_assertions import assert_no_special_chars


QUALITY_CRITERIA = [
    "The response talks about the workflow as a structure (jobs, edges, triggers), not about job-code-level error handling.",
    "The tone is warm and collaborative, not clinical or terse.",
    "If the response proposes a new email step, the rationale is plausible (e.g. mentions notification, summary, or alerting).",
]


def test_navigation_job_to_workflow(apollo_client: ApolloClient):
    existing_yaml = """..."""  # the pipeline yaml from the original test

    payload = build_workflow_chat_payload(
        existing_yaml=existing_yaml,
        history=[
            {"role": "user",      "content": "[pg:job_code/transform-data/http] Can you add error handling to this HTTP request?"},
            {"role": "assistant", "content": "I'll add try-catch error handling…"},
            {"role": "user",      "content": "[pg:job_code/transform-data/http] Also add retry logic with backoff"},
            {"role": "assistant", "content": "I'll add exponential backoff retry logic…"},
        ],
        user_message="Add a step to send the results via email",
        current_page="data-pipeline",
        previous_page={"type": "job_code", "name": "transform-data", "adaptor": "http"},
    )

    response = apollo_client.call("workflow_chat", payload)

    # ---- Structural assertions (deterministic, same as today) -------------
    assert response["response_yaml"], "Model should have generated YAML"
    yaml_obj = yaml.safe_load(response["response_yaml"])
    job_names = [j.get("name", "").lower() for j in yaml_obj["jobs"].values()]
    assert any("email" in n or "mail" in n or "send" in n for n in job_names), \
        "Email job not found in workflow"
    assert len(yaml_obj["jobs"]) > 3, "Expected a new job to be added"
    assert_no_special_chars(response["response_yaml"])

    response_text = response["response"].lower()
    assert not any(p in response_text for p in ["try", "catch", "retry", "backoff"]), \
        "Response should be about workflow structure, not job-code error handling"

    # ---- Quality assertions (LLM-judged) ----------------------------------
    verdict = judge.evaluate(
        criteria=QUALITY_CRITERIA,
        candidate=response,
        test_notes=__doc__,
    )
    assert verdict.passed, verdict.summary
```

### 3.2 What `QUALITY_CRITERIA` looks like to a non-technical contributor

The constant is a plain Python list of strings — visible at the top of every acceptance test file, named the same way every time. Editing it does not require touching anything else. Examples of additions a PO might make:

```python
QUALITY_CRITERIA = [
    "The response talks about the workflow as a structure…",
    "The tone is warm and collaborative, not clinical or terse.",
    "If the response proposes a new email step, the rationale is plausible.",
    # PO adds:
    "The response uses British English spelling.",
    "The response does not start with 'Certainly!' or 'Of course!'.",
]
```

The judge sees these verbatim plus the open-ended "flag anything else notable" instruction baked into the prompt, so a contributor never has to enumerate the full universe of things that could go wrong.

### 3.3 Example: job_chat adaptor context switching

```python
"""User was on a Salesforce page and asked 'how do I get data?'; assistant
answered with SOQL. User has now navigated to a DHIS2 page and asks the
same question. The model should switch context."""

from testing import judge
from testing.payloads import build_job_chat_payload


QUALITY_CRITERIA = [
    "The response is specifically about fetching data from DHIS2 — not from Salesforce.",
    "The response references DHIS2 concepts (tracker, data values, events, programs, etc.) rather than SQL/SOQL.",
    "The response does not assume the previous Salesforce context still applies.",
]


def test_adaptor_context_switching(apollo_client):
    payload = build_job_chat_payload(
        user_message="How do I get data?",
        history=[
            {"role": "user",      "content": "[pg:job_code/fetch-records/salesforce@9.0.3] How do I get data?"},
            {"role": "assistant", "content": "To get data from Salesforce, you can use `query()` with SOQL…"},
        ],
        current_job_code="fn(state => { return state; });",
        current_adaptor="@openfn/language-dhis2@8.0.7",
        current_page="fetch-data",
        suggest_code=False,
    )

    response = apollo_client.call("job_chat", payload)

    # Structural — history was correctly prefixed with the new page tag
    assert response["history"][2]["role"] == "user"
    assert "[pg:job_code/fetch-data/dhis2@8.0.7]" in response["history"][2]["content"]

    # Quality
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
```

### 3.4 Example: global_chat planner orchestration

```python
"""From-scratch CommCare→DHIS2 workflow with job code for both steps.
Expects planner to call workflow_agent then job_code_agent at least twice."""

import yaml

from testing import judge
from testing.payloads import build_global_chat_payload
from testing.responses import assert_routed_to, assert_agent_calls, get_attachment
from testing.yaml_assertions import assert_yaml_has_ids, assert_yaml_jobs_have_body


QUALITY_CRITERIA = [
    "The response explains the workflow's purpose in plain language a non-engineer can follow.",
    "The job code for the CommCare step uses CommCare adaptor functions, not generic JS.",
    "The job code for the DHIS2 step uses DHIS2 adaptor functions, not generic JS.",
    "The response does not leak the user's api_key or any secret-looking string.",
]


def test_commcare_to_dhis2_with_job_code(apollo_client):
    payload = build_global_chat_payload(
        user_message="Create a workflow that fetches patient cases from CommCare and registers them in DHIS2.",
        history=[],
    )
    response = apollo_client.call("global_chat", payload)

    # Structural — routing + orchestration
    assert_routed_to(response, "planner")
    assert_agent_calls(
        response["meta"],
        expected_agents=["planner", "workflow_agent", "job_agent"],
        min_job_code_calls=2,
    )

    # Structural — attached workflow yaml shape
    yaml_str = get_attachment(response, "workflow_yaml")
    assert yaml_str, "Expected a workflow_yaml attachment"
    parsed = yaml.safe_load(yaml_str)
    assert len(parsed["jobs"]) >= 2
    assert_yaml_has_ids(yaml_str)
    assert_yaml_jobs_have_body(yaml_str)

    # Quality
    verdict = judge.evaluate(criteria=QUALITY_CRITERIA, candidate=response, test_notes=__doc__)
    assert verdict.passed, verdict.summary
```

---

## 4. The judge

`services/testing/judge.py` is one module (~200 lines). Not an Apollo service.

### 4.1 Interface

```python
@dataclass
class CriterionResult:
    criterion: str
    passed: bool
    reasoning: str

@dataclass
class Verdict:
    passed: bool                        # all listed criteria passed AND no general_flags marked "regression"
    score: float                        # 0..1 — fraction of listed criteria passed
    criteria: list[CriterionResult]
    general_flags: list[str]            # judge-surfaced concerns not covered by criteria
    summary: str                        # multi-line; shown on pytest failure
    judge_usage: dict                   # input/output tokens

def evaluate(
    *,
    criteria: list[str],
    candidate: dict,                    # full chat-service response dict (response, response_yaml, attachments, meta, history)
    test_notes: str | None = None,      # usually __doc__ — context the judge sees but doesn't grade against
    model: str = "claude-sonnet-4-6",
) -> Verdict: ...
```

### 4.2 Prompt strategy

The judge prompt has two parts:

1. **Listed criteria.** For each criterion, return a JSON object with `passed` and `reasoning`.
2. **General flags.** A separate instruction: *"Additionally, flag anything else in the response that looks like a problem — tone drift, hedging, hallucinated facts, leaked secrets, broken formatting, or anything else that would make a reviewer pause — even if no criterion covers it. Return these as a `general_flags` array. Mark each flag with a severity: `note` (minor, informational) or `regression` (would surprise a reviewer or hurt a user). The verdict passes only if all listed criteria pass and there are no `regression`-severity flags."*

The judge sees `test_notes` (usually the test's docstring) as context but is instructed not to grade against it directly. JSON output is forced by prefilling `{`. Malformed JSON or judge refusal → `Verdict(passed=False, summary="judge_error: …")` surfaced loudly.

The full prompt text lives in the judge module's docstring; this section deliberately doesn't repeat it.

### 4.3 Why a helper and not a service

The judge has one caller today. A whole Apollo service + HTTP endpoint is overkill. If future callers appear (a ranker for `search_docsite`, a sanity-check step in a generator), promote `services/testing/judge.py` to `services/llm_evaluator/llm_evaluator.py` — a ~50-line reshape, not a redesign.

### 4.4 Self-tests for the judge

Per the unit-tier I/O policy (root `conftest.py` blocks `anthropic.Anthropic.__init__` for tests marked `unit`), tests that touch a mocked Anthropic transport are **service-tier**, not unit-tier:

- **Unit.** Pure helpers: prompt builder, JSON parser, criteria formatter. No Anthropic construction.
- **Service.** End-to-end `evaluate()` against a `MockAnthropic` transport — verifies criteria are threaded, general_flags are parsed, judge_error path works.

Open detail when the service tier lands: tests for code in `services/testing/` could live alongside the module (`services/testing/tests/`) or under a shared `services/tests/` umbrella (the precedent set for `services/util.py` helpers). Commit to one before the judge ships.

---

## 5. Payload builders

`services/testing/payloads.py` exposes one builder per chat service. The builders translate intuitive kwargs into the underlying JSON keys that each service expects today — so a contributor doesn't need to remember whether the field is `expression` or `current_code`, or whether navigation lives under `meta.last_page.adaptor` or `context.previous_adaptor`.

### 5.1 `build_workflow_chat_payload`

```python
def build_workflow_chat_payload(
    *,
    user_message: str | None = None,
    existing_yaml: str = "",
    history: list[dict] | None = None,
    errors: str | None = None,                     # alternative to user_message
    current_page: str | None = None,               # → context.page_name
    previous_page: dict | None = None,             # → meta.last_page
    api_key: str | None = None,
) -> dict: ...
```

### 5.2 `build_job_chat_payload`

```python
def build_job_chat_payload(
    *,
    user_message: str,
    history: list[dict] | None = None,
    current_job_code: str | None = None,           # → context.expression
    current_adaptor: str | None = None,            # → context.adaptor
    project_adaptors: list[str] | None = None,     # → context.adaptors
    current_page: str | None = None,               # → context.page_name
    project_id: str | None = None,                 # → context.projectId
    job_id: str | None = None,                     # → context.jobId
    input_data: Any = None,                        # → context.input
    output_data: Any = None,                       # → context.output
    log_data: Any = None,                          # → context.log
    rag_results: list[dict] | None = None,         # → meta.rag.search_results
    rag_queries: list[str] | None = None,          # → meta.rag.search_queries
    previous_page: dict | None = None,             # → meta.last_page
    suggest_code: bool | None = None,
    api_key: str | None = None,
    stream: bool | None = None,
) -> dict: ...
```

### 5.3 `build_global_chat_payload`

```python
def build_global_chat_payload(
    *,
    user_message: str,
    history: list[dict] | None = None,
    workflow_yaml: str | None = None,
    current_page: str | None = None,
    previous_page: dict | None = None,
    api_key: str | None = None,
) -> dict: ...
```

Each builder is ~30 lines of "if-not-None-set". The whole point is that the builder signature **is** the documentation — a contributor can read it once and know what's available without grepping the service code.

Adding a new payload field: one line in the builder + a one-line docstring entry. Removing one: same.

---

## 6. Response helpers

`services/testing/responses.py` lifts the cross-service helpers that today live duplicated in `services/global_chat/tests/test_utils.py`:

```python
def get_attachment(response: dict, name: str) -> str | None: ...
    # walks response["attachments"] for an entry with attachment_type == name

def assert_routed_to(response: dict, agent: str, *, context: str = "") -> None: ...
    # checks response["meta"]["router"]["agent"] (or wherever the router stamps it)

def assert_agent_calls(meta: dict, expected_agents: list[str], min_job_code_calls: int = 0, *, context: str = "") -> None: ...
    # the planner-chain assertion from test_planner_multistep.py — verifies
    # workflow_agent appears before any job_code_agent in meta["tool_calls"]
```

`testing.yaml_assertions` is already shipped in #486 and unchanged here.

---

## 7. Multi-run sampling

A test that benefits from sampling (tone, voice, anything where the LLM varies between runs) uses built-in pytest parametrization — nothing custom:

```python
@pytest.mark.parametrize("_run", range(3))
def test_navigation_job_to_workflow(apollo_client, _run):
    ...
```

Each value of `_run` becomes a separate pytest item. The arg is unused — the underscore signals that. Pytest's default output handles everything: per-item pass/fail in the run log, totals in the summary line, integration with `-k`, `pytest-xdist`, `--junitxml`. No `pytest_sessionfinish` tally, no custom marker, no policy — humans read the counts off pytest's normal output.

---

## 8. Langfuse integration

Langfuse is already wired on `add-langfuse`. Acceptance leans on it lightly:

### 8.1 Already in place (reused)

- `services/langfuse_util.py::should_track()` gates trace export. Payloads set `user.employee=True`.
- `@observe` on each chat service's `main()` — every acceptance call is auto-traced when `LANGFUSE_TRACING=true`.

### 8.2 What's new

1. **Session tagging.** A `langfuse_session` fixture in `services/testing/` reads the current test id + run index from the pytest item and sets `session_id = f"acceptance-{test_id}-run{run}"` and `tags = ["acceptance", test_id]` via `propagate_attributes`.
2. **Score push.** After the judge returns, write one score per run: `acceptance_pass` (0/1), `acceptance_score` (0..1), and `acceptance_general_flag_count`. Use Langfuse's Scores API directly from `services/testing/judge.py`.
3. **Cross-version comparison.** Native Langfuse dataset-runs view. The runner prints the URL on stdout at session end.

### 8.3 What's not built

- No Langfuse-hosted eval (we own the prompt).
- No hard dependency — acceptance runs offline if `LANGFUSE_PUBLIC_KEY` is unset OR `LANGFUSE_TRACING=false`; scores are skipped, tests still run.

---

## 9. How to run

```bash
# Run everything marked acceptance
poetry run pytest -m acceptance

# Run one service's acceptance tests
poetry run pytest services/workflow_chat/tests/acceptance

# Run one test, with output
poetry run pytest services/global_chat/tests/acceptance/test_planner_multistep.py -v

# Run against a staging server instead of spawning a local bun
APOLLO_TEST_BASE_URL=https://staging.apollo.openfn.org poetry run pytest -m acceptance
```

Requires the real `*_API_KEY` env vars (Anthropic, OpenAI, Pinecone) and — if Langfuse score push is wired — `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL`. Without Langfuse vars, tests still pass/fail normally; only the score push is skipped.

---

## 10. Cost control

- Run on demand only — every run is a deliberate human action.
- Default to no parametrization; tests opt into multi-run with `@pytest.mark.parametrize("_run", range(N))`.
- Judge defaults to `claude-sonnet-4-6`, not opus.
- Prompt caching on candidate calls.

Add a budget env or circuit breaker the first time a run surprises someone. Not on day one.

---

## 11. Migration of existing artefacts

| Existing | Migration target | Notes |
|---|---|---|
| `services/workflow_chat/tests/test_qualitative.py` | one file per `def test_*` under `services/workflow_chat/tests/acceptance/` | Each test keeps its existing structural asserts (`assert_yaml_*`, deep-equality, response negative-substring). Add `QUALITY_CRITERIA` derived from the test's `print(...)` description + reviewer instincts. Swap `subprocess.run` for `apollo_client.call("workflow_chat", payload)`. Swap nested-dict payload construction for `build_workflow_chat_payload(...)`. Add `judge.evaluate(...)`. |
| `services/job_chat/tests/test_qualitative.py` | one file per `def test_*` under `services/job_chat/tests/acceptance/` | Same pattern. `meta.rag` and `meta.last_page` map onto the builder's `rag_results` / `rag_queries` / `previous_page` kwargs. |
| `services/global_chat/tests/test_planner_multistep.py` | one file per `def test_*` under `services/global_chat/tests/acceptance/` | Keep `assert_routed_to`, `assert_agent_calls`, `get_attachment` — they move to `services/testing/responses.py` and import from there. The "vague request" tests (`test_vague_gmail_to_database`, `test_gsheets_transform_salesforce_with_cron`) currently have no quality asserts — exactly the case `QUALITY_CRITERIA` was designed for. |
| `services/job_chat/evaluation/questions.md` | optional — convert by hand into acceptance test files | Each `## question / ## adaptor / ## code` triple becomes a `build_job_chat_payload(...)` call. Quality criteria added by hand. |
| `temp_test_empty_response_guard.py` (in all three services, from #487) | service tier, not acceptance | Structural assertion against a mocked LLM — belongs in `tests/service/` once that tier lands. Flagged here so they don't accidentally get pulled into `acceptance/` during migration. |

Migration is opt-in, one test at a time. A test can ship to `acceptance/` before its `QUALITY_CRITERIA` are written — the structural assertions alone are valuable, the judge call can land empty (`criteria=[]`) and still surface general_flags.

---

## 12. Dependencies on the integration tier

Acceptance dispatches through a live bun server, so it shares infrastructure that the integration tier owns and ships first:

- `services/testing/apollo_client.py::ApolloClient` — wraps `.call()`, `.stream()`, `.ws()`.
- `services/testing/server.py::apollo_server` — session-scoped pytest fixture; spawns `bun run start`, polls `GET /` until ready, SIGTERM on teardown, honours `APOLLO_TEST_BASE_URL` for staging reuse.

Neither exists today. Acceptance can't run before they land. The judge module and payload builders **can** ship earlier — they're useful in any context that wants to evaluate an LLM response, not just acceptance.

---

## 13. Extensibility

Adding a new sub-agent or tool:

1. Ensure the service exposes `main()` at `services/<name>/<name>.py` (auto-mounts via `describe-modules.ts`).
2. Create `services/<name>/tests/acceptance/`.
3. If the payload shape is meaningfully different from existing chat services, add `build_<name>_payload(...)` to `services/testing/payloads.py`. Otherwise reuse an existing builder.
4. Drop test files in. The marker is auto-applied; pytest selects them via `-m acceptance`.

Adding a new judge model: pass `model="…"` to `judge.evaluate()`. No config file needed.

---

## 14. Relationship to integration

| Concern | Integration | Acceptance |
|---|---|---|
| Goal | Functional correctness | Quality, voice, style — *on top of* the structural checks |
| Assertions | Regex + shape | Same structural shape + `judge.evaluate(QUALITY_CRITERIA, ...)` |
| When run | Whenever the integration tier dictates | On demand only — never in an automated pipeline |
| Stability | Deterministic | Probabilistic (optional `@pytest.mark.parametrize("run", …)`) |
| Marker | `@pytest.mark.integration` (auto-applied by root conftest) | `@pytest.mark.acceptance` (auto-applied by root conftest) |
| Location | `services/<svc>/tests/integration/test_*.py` | `services/<svc>/tests/acceptance/test_*.py` |
| `test_hooks` | not used (real HTTP) | not used (real HTTP) |

**Overlap rule:** a test lives in exactly one tier. A test whose only purpose is structural is integration. A test that has *any* quality criterion the LLM judge should evaluate is acceptance — even if it also has structural asserts.

---

## 15. What this tier deliberately does NOT do

- **No top-level `tests/` tree.** Tests live under their service.
- **No `apollo/testing/` peer of `services/`.** The shared package is `services/testing/` — what shipped in #486.
- **No `services/llm_evaluator/` service.** Judge is a helper module.
- **No custom acceptance runner, no markdown-spec DSL.** The criteria field is a plain Python list; everything else is normal pytest.
- **No `bless` / `differ` / `migrate-questions` / `review` subcommands.**
- **No `golden/` git tree.** Model drift is tracked in Langfuse.
- **No HTML reporter.** `pytest-html` the day it's asked for.
- **No per-spec cost caps, budget estimator, `list`/`lint` commands.** Defer until bills say otherwise.
- **No exhaustive criteria.** Open-ended general-flag instruction in the judge prompt is the safety net.

---

## Summary

Acceptance tests are **Python files** in `services/<svc>/tests/acceptance/` — same shape as today's `test_qualitative.py`, with three additions: a `QUALITY_CRITERIA = [...]` module constant (the "edit me" surface for non-technical contributors), `build_<svc>_chat_payload(...)` for intuitive payload construction, and a `judge.evaluate(...)` call alongside the existing structural assertions. The judge grades the listed criteria *and* flags anything else notable, so the criteria list never has to be exhaustive. All existing structural assertions are preserved verbatim; nothing about how the current tests reason about yaml shape, page prefixes, tool-call sequencing, or attachments changes. The judge, payload builders, and response helpers live in the shared `services/testing/` package. Acceptance depends on the integration tier's `apollo_server` fixture + `ApolloClient`; it can't run before those land, though the judge and payload builders can ship earlier.
