# Section 3 — Integration Tests Architecture

**Scope:** `services/global_chat/`, `services/workflow_chat/`, `services/job_chat/` and future sub-agents / tools.

---

## 1. Purpose and boundaries

Integration tests exercise a chat service **end-to-end through the running bun server, with real model calls**. First tier in the pyramid where:

- Full stack: TypeScript `bridge.ts` → `spawn poetry run python services/entry.py` → `services/<name>/<name>.py:main()` → Anthropic / OpenAI / Pinecone network calls.
- Assertions are loose-to-moderate on content (regex, keyword presence, structural shape) and strict on payload shape (required fields, types, SSE event sequence, WS lifecycle).
- Slow (seconds to a minute each) and cost real money.

**What belongs here:** "does the service return a valid workflow yaml end-to-end over HTTP?", "does `/services/global_chat/stream` emit Anthropic-formatted SSE events in order?", "does WS `start → log* → complete` work for a real LLM run?", "does `test_errors` still map `ApolloError` to the right HTTP status?".

**What doesn't:**

| Concern | Correct tier |
|---|---|
| "Is this specific LLM answer good quality?" | acceptance |
| "Is the router prompt formatted right?" | service (mocked Anthropic) |
| "Does `AdaptorSpecifier.parse()` handle shorthand?" | unit |

**Dividing lines:**

- Service → integration: assertion depends on LLM-generated content.
- Integration → acceptance: assertion needs a judge LLM to evaluate.

---

## 2. Directory layout

Integration tests live alongside their service. **No top-level `tests/` tree.** One `*_integration.py` file per service:

```
services/<svc>/tests/
  test_<svc>_integration.py        # sync POST + SSE stream + WS in one file
```

Concretely:

```
services/global_chat/tests/test_global_chat_integration.py
services/workflow_chat/tests/test_workflow_chat_integration.py
services/job_chat/tests/test_job_chat_integration.py
```

**Cross-service / planner-chain end-to-end tests** live under `services/global_chat/tests/test_global_chat_integration.py` because `global_chat` owns the planner that dispatches to `workflow_chat` and `job_chat` over real HTTP. There's no separate "cross-service" home — the orchestrator hosts them.

**Smoke tests** for the platform itself (healthcheck `GET /`, 404 for unknown service, `test_errors` mapping) live under `services/echo/tests/test_echo_integration.py` since `echo` is the test-pipeline-verification service.

**One file per service** covers sync POST, SSE streaming, and WS in one place. Split by transport (`test_<svc>_stream_integration.py`) only if a single file gets unwieldy (>500 lines).

---

## 3. Server lifecycle

The session-scoped bun server fixture lives in **`testing/server.py`** (the shared helper package), not in a top-level conftest. Registered globally via `pytest_plugins = ["testing.server"]` in the root `apollo/conftest.py`.

### 3.1 Fixture

```python
@pytest.fixture(scope="session")
def apollo_server() -> ApolloServerHandle:
    ...
```

Handle:

```python
@dataclass
class ApolloServerHandle:
    base_url: str          # "http://127.0.0.1:<port>"
    port: int
    log_path: Path
```

**Startup:**

1. If `APOLLO_TEST_BASE_URL` is set, return a handle pointing at that URL. Lets us reuse a deployed staging server or a local `bun dev` during debugging.
2. Otherwise, allocate a port (bind-port-0 trick).
3. `subprocess.Popen(["bun", "run", "start"], env={..., "PORT": str(port)}, cwd=repo_root)`. Use `start` (not `dev`) — no hot-reload noise; matches production.
4. Drain stdout/stderr to `tmp/test-logs/<session-id>/bun.log`.
5. Poll `GET http://127.0.0.1:<port>/` with exponential backoff, 60s total cap.
6. Yield handle.

**Teardown:** SIGTERM → `wait(timeout=5)` → SIGKILL if needed. Flush log threads.

### 3.2 Scope

Session-scoped. Cold-start is ~2–5s; per-file or per-test would double runtime. Bun server is stateless between requests (each invocation spawns a fresh Python subprocess via `bridge.ts`), so sharing is safe.

No `pytest-xdist` parallelism on day one — Anthropic rate limits per API key. Add `-n auto --dist loadfile` with per-file scope when there's demand + headroom.

---

## 4. Environment and secrets

| Var | Purpose | Missing (dev) | Missing (CI) |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | All chat services | skip | fail |
| `OPENAI_API_KEY` | embeddings, search_docsite | skip | fail |
| `PINECONE_API_KEY` | search_docsite | skip | fail |
| `POSTGRES_URL` | services using `util.get_db_connection()` | skip | fail |
| `APOLLO_TEST_BASE_URL` | reuse deployed server | spawn | spawn |
| `LANGFUSE_TRACING` | flip Langfuse export on/off without changing credentials | unset → off | unset → off |

`require_env(*names)` helper in `testing/server.py`:

```python
def require_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if not missing:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(f"Missing env vars: {missing}")
    pytest.skip(f"Missing env vars: {missing}", allow_module_level=True)
```

Per-module: `require_env("ANTHROPIC_API_KEY")` at module top.

### 4.1 Secret sourcing in CI

- Repo secrets: `ANTHROPIC_API_KEY_TEST`, `OPENAI_API_KEY_TEST`, `PINECONE_API_KEY_TEST`, `POSTGRES_URL_TEST`.
- Dedicated test Pinecone namespace; ephemeral test Postgres. Never share the production `apollo-mappings` index / DB.
- Anthropic: separate API key with a low monthly cap, scoped to a test project.

### 4.2 Langfuse opt-in

Integration runs *can* trace to Langfuse but don't have to. Mechanism:

- `LANGFUSE_TRACING=true` → existing `@observe` decorators on production `main()` export traces.
- `LANGFUSE_TRACING=false` (or unset) → `@observe` short-circuits, no export.

In the CI workflow, leave `LANGFUSE_TRACING` unset by default — integration runs are clean. Add a `workflow_dispatch` input "Trace to Langfuse" (or a separate `run-integration-traced` PR label) to flip it on for the runs where someone wants to inspect traces afterwards. Credentials stay configured either way.

Integration writes traces only — no scores. Scoring is acceptance-tier territory.

---

## 5. HTTP client

`ApolloClient` lives in **`testing/server.py`** alongside the server fixture:

```python
class ApolloClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0): ...

    def call(self, service: str, payload: dict) -> dict: ...
        # POST /services/<service>. Raises ApolloHTTPError on non-2xx.

    def stream(self, service: str, payload: dict) -> Iterator[SSEEvent]: ...
        # POST /services/<service>/stream. Yields parsed SSE events.

    def ws(self, service: str, payload: dict) -> Iterator[WSEvent]: ...
        # WS /services/<service>. Yields events until "complete".
```

Dataclasses `SSEEvent(type, data)` and `WSEvent(event, type, data)` in the same file.

Dependencies: `httpx` (already in `poetry.lock`) and `websockets`. Install via a new `test-integration` poetry group:

```toml
[tool.poetry.group.test-integration]
optional = true

[tool.poetry.group.test-integration.dependencies]
websockets = "^13"
```

Installed in CI with `poetry install --with test-integration`.

Exposed fixture:

```python
@pytest.fixture
def client(apollo_server) -> ApolloClient:
    return ApolloClient(apollo_server.base_url)
```

Both integration and acceptance tiers use the same `client` fixture.

---

## 6. Assertion helpers

All in `testing/server.py` (or a small `testing/helpers.py` if it crowds the file):

- `collect_until_complete(stream, *, timeout=120)` → `(list[SSEEvent], final_payload)`.
- `assert_event_sequence(events, expected_types, *, strict=False)` — subsequence match by default.
- `accumulate_text_deltas(events)` — concatenate `content_block_delta` text.
- `assert_response_shape(response, required)` — `{"response": str, "usage": dict, "history": list}` style.
- `assert_response_contains(response, *regexes, field="response", flags=re.IGNORECASE)`.

YAML helpers (`assert_yaml_has_ids`, etc.) come from `testing/fixtures.py` — one canonical location.

---

## 7. Pytest configuration

Markers declared in `pyproject.toml [tool.pytest.ini_options].markers` — see overview §5 and service-tests plan §7.

Marker auto-applied by filename suffix `_integration.py` in the per-service or root conftest:

```python
def pytest_collection_modifyitems(config, items):
    for item in items:
        name = item.fspath.basename
        if name.endswith("_integration.py"):
            item.add_marker(pytest.mark.integration)
```

Authors don't write `@pytest.mark.integration`. Filename suffix is sufficient.

---

## 8. Opt-in commands

```bash
# Run the whole integration tier
poetry run pytest -m integration

# Run one service's
poetry run pytest services/global_chat/tests -m integration

# Smoke only
poetry run pytest services/echo/tests

# Against a deployed server
APOLLO_TEST_BASE_URL=https://apollo-staging.openfn.org poetry run pytest -m integration

# With Langfuse tracing on
LANGFUSE_TRACING=true poetry run pytest -m integration
```

---

## 9. CI integration

Integration and acceptance share one workflow: `.github/workflows/llm-tests.yaml`. Integration job runs on PR label `run-integration`, push to `main`, or `workflow_dispatch`. Acceptance job runs on PR label `run-acceptance` or `workflow_dispatch` only — never cron.

```yaml
name: llm-tests
on:
  pull_request:
    types: [labeled]
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      trace_langfuse:
        type: boolean
        default: false
        description: "Export traces to Langfuse"

concurrency:
  group: llm-${{ github.ref }}
  cancel-in-progress: true

jobs:
  integration:
    if: >-
      (github.event_name == 'pull_request' && github.event.label.name == 'run-integration')
      || github.event_name == 'push'
      || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      CI: "true"
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY_TEST }}
      OPENAI_API_KEY:    ${{ secrets.OPENAI_API_KEY_TEST }}
      PINECONE_API_KEY:  ${{ secrets.PINECONE_API_KEY_TEST }}
      POSTGRES_URL:      ${{ secrets.POSTGRES_URL_TEST }}
      LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY_TEST }}
      LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY_TEST }}
      LANGFUSE_BASE_URL:   ${{ secrets.LANGFUSE_BASE_URL }}
      LANGFUSE_TRACING: ${{ inputs.trace_langfuse == true && 'true' || 'false' }}
    steps:
      - uses: actions/checkout@v4
      - uses: oven-sh/setup-bun@v2
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - uses: snok/install-poetry@v1
      - run: bun install
      - run: poetry install --with test-integration
      - run: poetry run pytest -m integration -v --maxfail=5
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: integration-logs-${{ github.run_id }}
          path: tmp/test-logs/
          retention-days: 14

  acceptance:
    # see 4-acceptance-tests.md §6
    ...
```

`--maxfail=5` so a broken prompt doesn't burn the budget running every test. No `--timeout` plugin on day one.

---

## 10. Cost, retries, flakiness — not on day one

Deliberately deferred until a concrete bill or flake makes them necessary:

- No `cost_tracker.py`, `pricing.py`, budget env var, circuit breaker.
- No `pytest-rerunfailures` — flakes are signal.
- No `pytest-timeout` — `--maxfail=5` + 20-min workflow timeout is enough defence.
- No per-test `@pytest.mark.budget(usd=...)`.
- No `slow`, `flaky_model`, `needs_pinecone` markers — add individually when first needed.

Each of these has a real cost (learning curve, config churn, false alarms). Add one the first time its absence bites — not preemptively.

---

## 11. Streaming and WebSocket testing

Three transports need coverage. All three live in the same `test_<svc>_integration.py` file per service.

### Sync POST

```python
def test_workflow_chat_cron_trigger(client, sample_workflow_yaml):
    payload = make_workflow_chat_payload(
        existing_yaml=sample_workflow_yaml,
        content="Change the trigger to every day at midnight",
    )
    r = client.call("workflow_chat", payload)
    assert_response_shape(r, {"response": str, "response_yaml": str, "usage": dict})
    assert_yaml_has_ids(r["response_yaml"])
    yml = yaml.safe_load(r["response_yaml"])
    assert "cron" in yml["triggers"]
```

### SSE

```python
def test_workflow_chat_streams_events(client):
    payload = make_workflow_chat_payload(content="Generate a basic workflow", stream=True)
    events, final = collect_until_complete(client.stream("workflow_chat", payload))
    assert_event_sequence(events, [
        "message_start", "content_block_start", "content_block_delta",
        "content_block_stop", "message_delta", "message_stop",
    ])
    assert final is not None
    assert final["response"] == accumulate_text_deltas(events)
```

### WS

```python
def test_workflow_chat_ws_lifecycle(client):
    payload = make_workflow_chat_payload(content="Generate a basic workflow")
    events = list(client.ws("workflow_chat", payload))
    start = [e for e in events if e.event == "start"]
    complete = [e for e in events if e.event == "complete"]
    assert len(start) == 1 and len(complete) == 1
```

### Error paths

Lives in the smoke tests for the test_errors service:

```python
# services/echo/tests/test_echo_integration.py
def test_stream_emits_error_event(client):
    events = list(client.stream("test_errors", {"trigger": "RATE_LIMIT"}))
    err = next(e for e in events if e.type == "error")
    assert err.data["code"] == 429
```

---

## 12. Migration of existing tests

| Existing file | Destination |
|---|---|
| `services/*/tests/test_functions.py` (pure) | unit tier |
| `services/*/tests/test_pass_fail*.py` using `subprocess.run(entry.py)` | `services/<svc>/tests/test_<svc>_integration.py` — swap subprocess for `client.call()` |
| `services/*/tests/test_pass_fail*.py` using mocked sub-agents (`test_adaptor_version_passthrough.py`, `test_planner_subagent_clarification.py`) | service tier (mocked LLM) |
| `services/*/tests/test_qualitative.py` | mostly acceptance; a few with machine-checkable shape → integration |
| `services/*/tests/test_langfuse_tracing.py` | `services/<svc>/tests/test_<svc>_integration.py` — swap subprocess for `client.call()` |

Migration strategy: one service at a time, smallest first (workflow_chat). Keep old file for one PR with `pytest.mark.skip("migrated")`, delete in follow-up.

---

## 13. Extensibility

A new sub-agent or tool is a ~10-minute add:

1. Create `services/<name>/tests/test_<name>_integration.py`.
2. Use `client.call() / .stream() / .ws()` — no middleware changes; `describe-modules.ts` auto-mounts.
3. Add `make_<name>_payload` to `testing/fixtures.py` if needed.
4. No CI changes — workflow already collects `-m integration` across all services.

If a new tool requires a new external dep (new API key), add it to `require_env` and the CI secrets list.

---

## 14. What this tier deliberately does NOT do

- No top-level `tests/` tree — everything lives with the service.
- No cost tracker / pricing table / budget enforcement on day one.
- No retry plugin.
- No dual-API fixture (pytest fixture + context manager). Acceptance imports the same `client` fixture.
- No `APOLLO_TEST_QUICK` skip mode — `-m "not slow"` pattern can be added if needed, but no tests are marked `slow` on day one.
- No contract testing / VCR / recorded HAR. Possible future addition.

---

## Summary

One file per service: `services/<svc>/tests/test_<svc>_integration.py` covering sync + SSE + WS. Session-scoped `apollo_server` + `ApolloClient` in `testing/server.py`. Label-gated CI workflow shared with acceptance. Langfuse tracing is opt-in via `LANGFUSE_TRACING=true` (workflow input or env var). No cost tracking, no retries, no parallelism on day one. Add each when it's actually missed.
