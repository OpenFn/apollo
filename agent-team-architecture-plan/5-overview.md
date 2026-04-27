# Apollo Testing Architecture — Overview

**Supervisor:** team-lead
**Scope:** architecture (files, utils, fixtures, CI wiring) for a four-tier test framework covering `global_chat`, `workflow_chat`, `job_chat`, their tools, and any future sub-agent / tool services. Specific tests are NOT designed here.

Deep detail lives in:

- `1-unit-tests.md` — pure-function tests, free, every push.
- `2-service-tests.md` — `main()` with a mocked Anthropic HTTP client, free, every push.
- `3-integration-tests.md` — HTTP to the running bun server with real LLMs, label-gated.
- `4-acceptance-tests.md` — markdown specs judged by an LLM helper, manually triggered only.

---

## 1. The four tiers at a glance

| Tier | Transport | LLM | Asserts on | Runs on |
|---|---|---|---|---|
| **Unit** | direct import of one function | none | function output | every push |
| **Service** | direct `main(data, test_hooks)` | mocked via injected `httpx.MockTransport` | code path, mock call args, payload shape | every push |
| **Integration** | HTTP / SSE / WS via running bun server | real | response shape + loose regex on content | push to `main`, PR label `run-integration`, manual |
| **Acceptance** | HTTP via running bun server | real + judge LLM | natural-language criteria graded by judge | PR label `run-acceptance`, manual (`workflow_dispatch`). **Never automatic** — humans decide when a change is big enough to warrant a run. |

**Sharp dividing lines:**

- Content assertion depends on *what the LLM wrote* → integration or acceptance (not service).
- Content assertion needs a judge LLM → acceptance (not integration).
- Test exercises `main()` → service or integration (not unit).
- Test needs the bun server → integration or acceptance (not unit or service).

---

## 2. Directory layout

Every test lives under the service it relates to. One `tests/` folder per service holds all four tiers.

```
apollo/
├── conftest.py                             # root: dummy api keys, register shared fixtures, markdown spec collector
│
├── testing/                                # Shared test helpers — peer to services/, not a service itself
│   ├── __init__.py
│   ├── anthropic_mock.py                   # MockAnthropic (regex → response) + tool_use helper + record_tool_call; documents the `test_hooks` dict keys
│   ├── fixtures.py                         # pytest fixtures (mock client, test_hooks factory, payloads, yaml assertions)
│   ├── server.py                           # apollo_server fixture + ApolloClient (sync / sse / ws)
│   ├── judge.py                            # small LLM-as-judge helper for acceptance specs
│   └── fixtures/                           # sample yaml/json shared across services
│       ├── workflows/*.yaml
│       └── histories/*.json
│
├── services/
│   └── <chat-service>/                     # global_chat, workflow_chat, job_chat
│       ├── <chat-service>.py               # main() gains optional `test_hooks` 2nd arg (default None)
│       └── tests/
│           ├── conftest.py                 # auto-marks by filename suffix and acceptance/ folder
│           ├── test_<module>_unit.py       # tier 1 — pure functions, marker: unit
│           ├── test_<module>_service.py    # tier 2 — main() with mocked anthropic, marker: service
│           ├── test_<svc>_integration.py   # tier 3 — sync + stream + ws, marker: integration
│           └── acceptance/                 # tier 4 — markdown specs, marker: acceptance
│               └── *.md                    # question + data + natural-language assertions
│
├── .github/workflows/
│   ├── tests.yaml                          # unit + service, every push (free)
│   └── llm-tests.yaml                      # integration + acceptance, label-gated / manual only (no cron, no schedule)
│
└── pyproject.toml                          # [tool.pytest.ini_options]: markers, pythonpath=["services", "."]
```

**Decisions worth knowing:**

- **All tests live with their service.** `services/<svc>/tests/` holds unit + service + integration tests for that service, plus an `acceptance/` subfolder of markdown specs. No top-level `tests/` tree.
- **Cross-service work lives with the orchestrator.** Planner-chain end-to-end integration tests live under `services/global_chat/tests/test_global_chat_integration.py` because `global_chat` owns the planner. Cross-service acceptance specs (refusals, safety) live under `services/global_chat/tests/acceptance/`.
- **One shared helper package: `apollo/testing/`.** A peer of `services/` and `platform/`, not a service. Server fixture, ApolloClient, mock anthropic, judge, payload builders, yaml assertions — all here.
- **Filename suffix + folder name carry tier intent.** `*_unit.py` → unit, `*_service.py` → service, `*_integration.py` → integration, `acceptance/*.md` → acceptance. Marker auto-applied by conftest. Authors never write `@pytest.mark.X` manually.
- **No `llm_evaluator` Apollo service.** The judge is `testing/judge.py`. Promote to a service the day it has a non-test caller.
- **`test_hooks` second-arg stays.** Load-bearing production change; cheap. `test_hooks is None` is byte-identical to today.

---

## 3. The `test_hooks` second-arg pattern (service tier's anchor)

Every chat service's `main()` gains an optional second argument:

```python
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict: ...
```

- **HTTP path is untouched.** `entry.py` calls `m.main(data)` with one positional arg. Because `test_hooks` defaults to `None`, the bridge never sees it.
- **Only direct-Python callers (pytest) set `test_hooks`.** Integration and acceptance tiers don't use it (they go through HTTP, which strips `test_hooks`). Unit tier doesn't use it (unit tests never call `main()`).

`test_hooks` is a plain Python `dict` (not a formal type). Its recognised keys are documented as a docstring in `testing/anthropic_mock.py`:

- `anthropic_http_client` — an `httpx.Client` backed by `httpx.MockTransport`. Built by `MockAnthropic`, which matches each request's latest user message text against test-registered regex → response pairs (no match → `AssertionError`). Threaded into every `Anthropic(api_key=..., http_client=...)` constructor site via a new `services/util.py::build_anthropic_client()` factory. The planner's internal tool-use loop (multiple Anthropic calls per `main()`) is covered by the same mechanism — each round has different latest-user-message text, so different regexes match. See `2-service-tests.md` §3.
- `tool_calls` — a test-allocated `list[dict]` that production code appends to as breadcrumbs when present.
- `tool_stubs` — a `dict[str, Callable]` keyed by tool name. The planner consults it before dispatching a tool; if a stub is registered, it's called instead of the real tool. Today only used for `search_documentation` (which otherwise hits Pinecone + OpenAI). See `2-service-tests.md` §5.

No sub-agent stub registry, no tool stub registry, no `seed`, no `disable_langfuse` — the shape starts minimal and grows only when a test can't be written without it.

Minimal production-code edits: the three chat services' `main()`, their `AnthropicClient`/`RouterAgent`/`PlannerAgent` constructors (one-line swap to `build_anthropic_client(api_key, test_hooks)`), and the new factory in `services/util.py`.

---

## 4. Server lifecycle

`testing/server.py` exposes a session-scoped pytest fixture `apollo_server` that:

- Honours `APOLLO_TEST_BASE_URL` to reuse a running staging server or local `bun dev`.
- Otherwise spawns `bun run start` on an OS-allocated port, polls `GET /` until 200, yields `(base_url, port)`.
- On teardown: SIGTERM, 5s wait, SIGKILL if needed. Drains stdout/stderr to `tmp/test-logs/`.

`ApolloClient` (also in `testing/server.py`) wraps `.call()`, `.stream()`, `.ws()`. Function-scoped `client` fixture binds to the session server. Both integration and acceptance use the same fixture.

Registered globally via `pytest_plugins = ["testing.fixtures", "testing.server"]` in the root `apollo/conftest.py`.

---

## 5. Test runner and commands

Everything is pytest. Acceptance markdown specs are collected by a `pytest_collect_file` hook in the root `apollo/conftest.py`. No custom runner.

```bash
# Dev default — free, fast
poetry run pytest -m "unit or service"

# Run just one tier
poetry run pytest -m unit
poetry run pytest -m service
poetry run pytest -m integration         # opt-in
poetry run pytest -m acceptance          # opt-in

# Run all tests for a single service (any tier)
poetry run pytest services/global_chat/tests

# Run one tier within one service
poetry run pytest services/global_chat/tests -m integration
poetry run pytest services/global_chat/tests/acceptance
```

TypeScript platform tests continue to run via `bun test`. Unchanged.

---

## 6. CI integration

Two workflow files:

| File | Runs | Trigger | Secrets | Timeout |
|---|---|---|---|---|
| `.github/workflows/tests.yaml` | `pytest -m "unit or service"` | every push, every PR | **none** (deliberate — mocks must not hit real APIs; missing `ANTHROPIC_API_KEY` is a loud failure) | 10 min |
| `.github/workflows/llm-tests.yaml` | `pytest -m "integration or acceptance"` | **Integration:** PR label `run-integration`, push to `main`, `workflow_dispatch`. **Acceptance:** PR label `run-acceptance` or `workflow_dispatch` only — never cron, schedule, or push. | `ANTHROPIC_API_KEY_TEST`, `OPENAI_API_KEY_TEST`, `PINECONE_API_KEY_TEST`, `POSTGRES_URL_TEST`, `LANGFUSE_*_TEST` | 45 min |

Design invariant: **the fast job has no `ANTHROPIC_API_KEY` env var**. If a service test accidentally constructs a real Anthropic client (because someone forgot to thread `test_hooks`), the SDK errors on missing-key — a loud failure is free defence-in-depth against mocked-test leaks.

Cost controls for the LLM workflow are intentionally out of day-one scope: start with `--maxfail=5` and a 45-min timeout; add budget tracking the first time a bill surprises someone.

---

## 7. Conventions that hold across all tiers

- **Layer marker auto-apply.** Per-service `services/<svc>/tests/conftest.py` uses `pytest_collection_modifyitems` to tag tests by filename suffix (`_unit.py` / `_service.py` / `_integration.py`) and folder (`acceptance/`). Authors never write `@pytest.mark.X` manually.
- **No Langfuse export from free-tier tests.** `LANGFUSE_TRACING=false` set in unit/service runs.
- **Dummy API keys for free-tier tests.** `ANTHROPIC_API_KEY="unit-test-dummy"` so imports don't crash but any accidentally-real call fails loud.
- **`pythonpath = ["services"]`.** Kills the `sys.path.insert(...)` boilerplate at the top of every existing test file.

---

## 8. Extensibility — adding a new sub-agent or tool

1. Add `services/<new_name>/<new_name>.py` with `main(data, test_hooks=None)`. Auto-mounted by `describe-modules.ts`.
2. Create `services/<new_name>/tests/conftest.py` — copy from an existing service.
3. Add files as needed: `test_<module>_unit.py`, `test_<module>_service.py`, `test_<new_name>_integration.py`, `acceptance/*.md`.

No changes needed in pyproject, CI, or shared helpers. Discovery is zero-config — pytest already crawls `services/*/tests/` and the markdown collector finds any `acceptance/` folder.

---

## 9. Implementation order (recommended)

1. **Scaffolding.** Create `testing/` (skeleton — `anthropic_mock.py`, `fixtures.py`, `server.py`, `judge.py`), root `apollo/conftest.py`, `[tool.pytest.ini_options]` block in pyproject. One PR — unblocks everything else.
2. **Unit tier.** Migrate `services/workflow_chat/tests/test_functions.py` → `test_workflow_chat_functions_unit.py` as the worked example. Wire `tests.yaml` with just `-m unit`. Green CI on every push.
3. **Service tier.** Add `test_hooks=None` to the three chat services' `main()`. Add `services/util.py::build_anthropic_client()`. Build `MockAnthropic`. Extend `tests.yaml` to `-m "unit or service"`. Migrate the first `pass_fail` test whose assertion doesn't depend on content.
4. **Integration tier.** Add `testing/server.py` (server fixture + `ApolloClient`). Create `llm-tests.yaml`. Migrate the first cross-service end-to-end test into `services/global_chat/tests/test_global_chat_integration.py`. Secrets wired.
5. **Acceptance tier.** Add `testing/judge.py` and the markdown collector hook in the root conftest. Drop the first 2–3 hero specs into `services/global_chat/tests/acceptance/`. First manual run green (`workflow_dispatch`).

Each step is an independent PR. Nothing here blocks shipping production features in between.

---

## 10. What this architecture deliberately does NOT do

- Does not design specific tests. That's the next phase.
- Does not modify production code beyond the `test_hooks` second-arg + `build_anthropic_client` factory.
- Does not replace `bun:test` for TypeScript.
- Does not create a top-level `tests/` tree. Everything lives with the service.
- Does not create a separate `llm_evaluator` service. Judge is a helper module.
- Does not build a custom acceptance runner with `bless`/`differ`/`migrate-questions`/etc. Specs are markdown, collection is pytest, judge writes scores to Langfuse via its existing SDK — that's it.
- Does not track golden answers as a separate git tree. If we want regression diffing later, Langfuse's native dataset-run comparison is the primitive.
- Does not build cost tracking, pricing tables, retry plugins, or circuit breakers on day one. Add each the first time its absence costs something.
- Does not gate merges on coverage percentages.

---

## Summary

Four tiers, one home (`services/<svc>/tests/`), one shared Python helper package (`testing/`), zero new Apollo services, two CI workflows. The `test_hooks` second-arg pattern is the single architectural change to production code; everything else is additive. Adding a new sub-agent or tool is a ~10-minute task with no framework edits.
