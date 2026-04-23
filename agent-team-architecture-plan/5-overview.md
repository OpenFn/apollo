# Apollo Testing Architecture — Overview (Simplified)

**Supervisor:** team-lead
**Scope:** architecture (files, utils, fixtures, CI wiring) for a four-tier test framework covering `global_chat`, `workflow_chat`, `job_chat`, their tools, and any future sub-agent / tool services. Specific tests are NOT designed here.

> **Note on provenance.** An earlier draft of this overview (and its four section files) grew a lot of scaffolding that wasn't in the original brief — a dedicated `llm_evaluator` service, a custom acceptance runner with `bless`/`differ`/`langfuse-sink`/`migrate-questions` subcommands, golden-answer trees, cost-tracker/pricing/retry plugins, dual homes for shared helpers, etc. This revision strips the plan back to what the original task actually asked for. The four tiers, the `test_hooks` second-arg pattern, the mocked Anthropic HTTP client, and one shared helper package remain. Everything else is deferred until a concrete need for it appears.

Deep detail lives in:

- `1-unit-tests.md` — pure-function tests, free, every push.
- `2-service-tests.md` — `main()` with a mocked Anthropic HTTP client, free, every push.
- `3-integration-tests.md` — HTTP to the running bun server with real LLMs, label-gated.
- `4-acceptance-tests.md` — markdown specs judged by an LLM helper, manually triggered only.

---

## 1. The four tiers at a glance

| Tier | Transport | LLM | Asserts on | Cost | Runs on |
|---|---|---|---|---|---|
| **Unit** | direct import of one function | none | function output | free | every push |
| **Service** | direct `main(data, test_hooks)` | mocked via injected `httpx.MockTransport` | code path, mock call args, payload shape | free | every push |
| **Integration** | HTTP / SSE / WS via running bun server | real | response shape + loose regex on content  | push to `main`, PR label `run-integration`, manual |
| **Acceptance** | HTTP via running bun server | real + judge LLM | natural-language criteria graded by judge | PR label `run-acceptance`, manual (`workflow_dispatch`). **Never automatic** — humans decide when a change is big enough to warrant a run. |

**Sharp dividing lines:**

- Content assertion depends on *what the LLM wrote* → integration or acceptance (not service).
- Content assertion needs a judge LLM → acceptance (not integration).
- Test exercises `main()` → service or integration (not unit).
- Test needs the bun server → integration or acceptance (not unit or service).

---

## 2. Directory layout

```
apollo/
├── services/
│   ├── _testing/                           # Shared python test helpers. Underscore hides it from describe-modules auto-mount.
│   │   ├── __init__.py
│   │   ├── anthropic_mock.py               # MockAnthropicClient + canned response builders; documents the `test_hooks` dict keys
│   │   ├── fixtures.py                     # pytest fixtures (mock client, test_hooks factory, payloads, yaml assertions)
│   │   └── fixtures/                       # sample yaml/json shared across services
│   │       ├── workflows/*.yaml
│   │       └── histories/*.json
│   │
│   ├── <chat-service>/                     # global_chat, workflow_chat, job_chat
│   │   ├── <chat-service>.py               # main() gains optional `test_hooks` 2nd arg (default None)
│   │   └── tests/
│   │       ├── conftest.py                 # re-exports shared fixtures; auto-marks by filename suffix
│   │       ├── test_<module>_unit.py       # tier 1 — pure functions, marker: unit
│   │       └── test_<module>_service.py    # tier 2 — main() with mocked anthropic, marker: service
│   │
│   └── conftest.py                         # root: dummy api keys, register shared fixtures
│
├── tests/
│   ├── conftest.py                         # session-scoped bun_server + ApolloClient (sync / sse / ws) + marker auto-apply
│   ├── integration/                        # tier 3 — real LLM over HTTP, marker: integration
│   │   └── <chat-service>/
│   │       └── test_<chat-service>.py
│   └── acceptance/                         # tier 4 — markdown specs judged by LLM, marker: acceptance
│       ├── conftest.py                     # collects *.md specs as pytest items, runs judge
│       ├── judge.py                        # small LLM-as-judge helper (not a whole service)
│       └── specs/
│           └── <chat-service>/
│               └── *.md                    # question + data + natural-language assertions
│
├── .github/workflows/
│   ├── tests.yaml                          # unit + service, every push (free)
│   └── llm-tests.yaml                      # integration + acceptance, label-gated / manual only (no cron, no schedule)
│
└── pyproject.toml                          # [tool.pytest.ini_options]: markers, pythonpath=["services"]
```

**Decisions worth knowing:**

- **One shared helper package: `services/_testing/`.** Underscore-prefixed so `platform/src/util/describe-modules.ts` doesn't auto-mount it. Everything any tier imports lives here. No separate `tests/_common/`.
- **No `unit/` vs `service/` subdirs per service.** Filename suffix (`_unit.py` / `_service.py`) + auto-marker in `conftest.py` is enough while each service has <20 test files. Promote to subdirs only when someone has a reason.
- **No `llm_evaluator` Apollo service.** The judge is a helper module (`tests/acceptance/judge.py`) used by the acceptance conftest. If the judge logic ever needs to be callable from another Apollo service, promote it then.
- **Server fixture + HTTP client live in `tests/conftest.py`, not a separate package.** They can move to a package the day someone imports them from a third tier. Today, integration and acceptance both import from the one place.
- **`test_hooks` second-arg stays.** It's the load-bearing production change and it's cheap — `test_hooks is None` is byte-identical to today.

---

## 3. The `test_hooks` second-arg pattern (service tier's anchor)

Every chat service's `main()` gains an optional second argument:

```python
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict: ...
```

- **HTTP path is untouched.** `entry.py` calls `m.main(data)` with one positional arg. Because `test_hooks` defaults to `None`, the bridge never sees it.
- **Only direct-Python callers (pytest) set `test_hooks`.** Integration and acceptance tiers don't use it (they go through HTTP, which strips `test_hooks`). Unit tier doesn't use it (unit tests never call `main()`).

`test_hooks` is a plain Python `dict` (not a formal type). Its recognised keys are documented as constants + docstring in `services/_testing/anthropic_mock.py`:

- `anthropicHttpClient` — an `httpx.Client` backed by `httpx.MockTransport`; threaded into every `Anthropic(api_key=..., http_client=...)` constructor site via a new `services/util.py::build_anthropic_client()` factory.
- `toolCalls` — a test-allocated `list[dict]` that production code appends to as breadcrumbs when present. Added only when the first test actually needs it.

No sub-agent stub registry, no tool stub registry, no `seed`, no `disableLangfuse` — the shape starts minimal and grows only when a test can't be written without it. Start small; add keys when a concrete test demands them.

Minimal production-code edits: the three chat services' `main()`, their `AnthropicClient`/`RouterAgent`/`PlannerAgent` constructors (one-line swap to `build_anthropic_client(api_key, test_hooks)`), and the new factory in `services/util.py`.

---

## 4. Server lifecycle

`tests/conftest.py` exposes a session-scoped pytest fixture `apollo_server` that:

- Honours `APOLLO_TEST_BASE_URL` to reuse a running staging server or local `bun dev`.
- Otherwise spawns `bun run start` on an OS-allocated port, polls `GET /` until 200, yields `(base_url, port)`.
- On teardown: SIGTERM, 5s wait, SIGKILL if needed. Drains stdout/stderr to `tmp/test-logs/`.

`ApolloClient` (also in `tests/conftest.py`) wraps `.call()`, `.stream()`, `.ws()`. Function-scoped `client` fixture binds to the session server. Acceptance uses the same fixture — no dual-API context manager.

---

## 5. Test runner and commands

Everything is pytest. Both the integration and acceptance tiers collect via standard pytest; acceptance's collection of markdown specs is done by a small `pytest_collect_file` hook in `tests/acceptance/conftest.py`. No custom runner.

```bash
# Dev default — free, fast
poetry run pytest -m "unit or service"

# Run just one tier
poetry run pytest -m unit
poetry run pytest -m service
poetry run pytest tests/integration -m integration      # opt-in
poetry run pytest tests/acceptance -m acceptance        # opt-in

# Run tests for a single service
poetry run pytest services/global_chat/tests
poetry run pytest tests/integration/global_chat
poetry run pytest tests/acceptance/specs/global_chat
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

- **Layer marker auto-apply.** `tests/conftest.py` and each service's `tests/conftest.py` use `pytest_collection_modifyitems` to add the marker based on filename suffix (`_unit.py` / `_service.py`) or folder (`tests/integration/`, `tests/acceptance/`). Test authors never write `@pytest.mark.unit` manually.
- **No Langfuse export from free-tier tests.** `LANGFUSE_TRACING=false` set in unit/service runs.
- **Dummy API keys for free-tier tests.** `ANTHROPIC_API_KEY="unit-test-dummy"` so imports don't crash but any accidentally-real call fails loud.
- **`pythonpath = ["services"]`.** Kills the `sys.path.insert(...)` boilerplate at the top of every existing test file.

---

## 8. Extensibility — adding a new sub-agent or tool

1. Add `services/<new_name>/<new_name>.py` with `main(data, test_hooks=None)`. Auto-mounted by `describe-modules.ts`.
2. Create `services/<new_name>/tests/` with a thin conftest re-exporting shared fixtures. Add `test_<module>_unit.py` / `test_<module>_service.py` as needed.
3. Create `tests/integration/<new_name>/test_<new_name>.py` using the shared `client` fixture.
4. Create `tests/acceptance/specs/<new_name>/` and drop markdown spec files.

No changes needed in pyproject, CI, or shared helpers. Discovery is zero-config everywhere.

---

## 9. Implementation order (recommended)

1. **Scaffolding.** Create `services/_testing/` (three files), root `services/conftest.py`, `[tool.pytest.ini_options]` block in pyproject. One PR — unblocks everything else.
2. **Unit tier.** Migrate `services/workflow_chat/tests/test_functions.py` → `test_workflow_chat_functions_unit.py` as the worked example. Wire `tests.yaml` with just `-m unit`. Green CI on every push.
3. **Service tier.** Add the `test_hooks` second arg to all three chat services' `main()` (backward-compatible default). Add `services/util.py::build_anthropic_client()`. Build `MockAnthropicClient`. Extend `tests.yaml` to `-m "unit or service"`. Migrate the first `pass_fail` test whose assertion doesn't depend on content.
4. **Integration tier.** Add `tests/conftest.py` (server fixture + `ApolloClient`). Create `llm-tests.yaml`. Migrate the first cross-service end-to-end test. Secrets wired.
5. **Acceptance tier.** Add `tests/acceptance/judge.py` + `tests/acceptance/conftest.py` with the markdown spec collector. Define the first 2–3 hero specs (PO authors). First manual run green (`workflow_dispatch`).

Each step is an independent PR. Nothing here blocks shipping production features in between.

---

## 10. What this architecture deliberately does NOT do

- Does not design specific tests. That's the next phase.
- Does not modify production code beyond the `test_hooks` second-arg + `build_anthropic_client` factory.
- Does not replace `bun:test` for TypeScript.
- Does not create a separate `llm_evaluator` service. Judge is a helper module.
- Does not build a custom acceptance runner with `bless`/`differ`/`migrate-questions`/etc. Specs are markdown, collection is pytest, judge writes scores to Langfuse via its existing SDK — that's it.
- Does not track golden answers as a separate git tree. If we want regression diffing later, Langfuse's native dataset-run comparison is the primitive.
- Does not build cost tracking, pricing tables, retry plugins, or circuit breakers on day one. Add each the first time its absence costs something.
- Does not gate merges on coverage percentages.

---

## Summary

Four tiers, two top-level homes (`services/<svc>/tests/` for free-tier tests; `tests/` for server-required tiers), one shared Python helper package (`services/_testing/`) with three files, zero new Apollo services, two CI workflows. The `test_hooks` second-arg pattern is the single architectural change to production code; everything else is additive. Adding a new sub-agent or tool is a ~10-minute task with no framework edits.
