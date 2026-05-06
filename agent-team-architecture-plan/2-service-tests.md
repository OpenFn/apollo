# Section 2 — Service Tests Architecture

> Scope: `services/global_chat/`, `services/workflow_chat/`, `services/job_chat/`, and the tools / sub-agents they invoke.

---

## 1. Naming and position

**Service tests** — direct calls to `main()` with Anthropic HTTP calls mocked. One rung above unit, one below integration.

| Tier       | Scope             | LLM calls | HTTP layer | Cost | Runs on PR push |
|------------|-------------------|-----------|------------|------|-----------------|
| unit       | single function   | no        | no         | free | yes             |
| **service** | **`main()` end-to-end** | **mocked** | **no (direct python)** | **free** | **yes**  |
| integration | `main()` via server | real    | yes        | $$   | manual / label  |
| acceptance  | behaviour spec    | real      | yes        | $$$  | nightly / manual |

Service tests verify *logic and information flow*: payload validation, routing, prompt assembly, tool-call orchestration, sub-agent invocation, history/usage aggregation, error paths, headers, api_key passthrough. They do **not** verify model quality.

---

## 2. The `test_hooks` second argument

`main()` gains an optional second positional arg:

```python
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict: ...
```

`entry.py` keeps calling `m.main(data)` with one arg — the HTTP path never sees `test_hooks`. Production behaviour when `test_hooks is None` is byte-identical to today.

The dict has three documented keys, all optional (docstring in `services/testing/anthropic_mock.py`):

- `"anthropic_http_client"` — `httpx.Client` backed by `httpx.MockTransport`. Threaded into every `Anthropic(...)` constructor via `build_anthropic_client`.
- `"tool_calls"` — `list[dict]` the test allocates. Production appends breadcrumbs via `record_tool_call`.
- `"tool_stubs"` — `dict[str, Callable]` keyed by tool name. When the planner dispatches a tool, a stub (if registered) is called instead. Today only used for `search_documentation`.

Sub-agent stubbing isn't supported — sub-agents run under the same shared mock client.

Sites that thread `test_hooks` through:

- `services/job_chat/job_chat.py` — `AnthropicClient.__init__`
- `services/workflow_chat/workflow_chat.py` — `AnthropicClient.__init__`
- `services/global_chat/router.py` — `RouterAgent.__init__`
- `services/global_chat/planner.py` — `PlannerAgent.__init__`
- `services/global_chat/subagent_caller.py` — forwards to sub-agent `main()`

---

## 3. Mock Anthropic HTTP client

### 3.1 Factory in `services/util.py`

```python
def build_anthropic_client(api_key: str, test_hooks: Optional[dict] = None) -> Anthropic:
    http_client = (test_hooks or {}).get("anthropic_http_client")
    kwargs = {"api_key": api_key}
    if http_client is not None:
        kwargs["http_client"] = http_client
    return Anthropic(**kwargs)
```

Every `AnthropicClient` / `RouterAgent` / `PlannerAgent` constructor swaps `Anthropic(api_key=...)` for `build_anthropic_client(api_key, test_hooks)`.

### 3.2 `MockAnthropic` in `services/testing/anthropic_mock.py`

Thin wrapper over `httpx.MockTransport`. Tests register regex → response pairs; on each Anthropic request the mock matches the latest user message text against registered patterns and returns the first match. No new runtime dep — `httpx.MockTransport` is built into httpx (already in `poetry.lock`).

```python
mock = MockAnthropic()
mock.set_response(r"haiku", "sure, here's a haiku")
mock.set_response(r"create workflow", tool_use("call_workflow_agent", {...}))
test_hooks = test_hooks_factory(anthropic=mock)
main(payload, test_hooks)
assert mock.last_request.headers["x-api-key"] == "sk-test"
```

Design choices:

- **First-match-wins.** Order specific patterns before general ones.
- **Loud no-match.** Raises `AssertionError` with the unmatched text + registered patterns.
- **Captured requests.** `mock.requests` (list) and `mock.last_request` for assertions on outbound headers, body shape, system prompt, `cache_control`, etc.

Two private helpers in the same file:

- `_latest_user_text(messages)` — last `role=user` message's text + tool_result content. Matching against `tool_result` text is what makes the planner's internal loop work.
- `_build_message_body(response)` — wraps response in standard Anthropic message envelope.

A `tool_use(name, input)` helper builds tool_use content blocks for `set_response`.

### 3.3 Planner internal loop

`main()` is one user turn, but the planner calls Anthropic multiple times within that turn (call → tool_use → run tool → call with tool_result → ... until `end_turn`). Each round has different content in the latest user message, so regex matching naturally resolves it.

When a sub-agent is invoked inside this loop, its own `main()` runs under the *same* mock client. Tests register regexes covering both parent and child expected user messages on one mock — no sub-agent stub registry needed.

### 3.4 Streaming (deferred)

Streaming-mock support is out of scope. Defer until the first service test for a streaming code path actually needs it. Integration tier covers stream behaviour.

---

## 4. Tool-call breadcrumbs

`record_tool_call` lives in `services/util.py` next to `build_anthropic_client` (production code never imports from `testing/`):

```python
def record_tool_call(test_hooks: Optional[dict], entry: dict) -> None:
    if test_hooks is None:
        return
    crumbs = test_hooks.get("tool_calls")
    if crumbs is not None:
        crumbs.append(entry)
```

Dispatch sites (`planner._execute_tool`, `router.route_and_execute`) call `record_tool_call(test_hooks, {"tool": ..., "input": ...})`. Two dict lookups when `test_hooks is None` — negligible.

Tests read:

```python
assert [c["tool"] for c in test_hooks["tool_calls"]] == ["router_decision", "call_workflow_agent"]
```

---

## 5. Tool stubs

Most planner tools don't need stubbing. `call_workflow_agent` and `call_job_code_agent` inherit `test_hooks` and run the sub-agent's own mocked `main()`. `inspect_job_code` is pure local code. The one tool that does need stubbing is **`search_documentation`** — without a stub it would hit Pinecone + OpenAI on every service test.

`planner._execute_tool` checks for a stub at the top of dispatch:

```python
stub = (self._test_hooks or {}).get("tool_stubs", {}).get(tool_use_block.name)
if stub is not None:
    tool_result = stub(tool_use_block.input)
else:
    # original dispatch by name
    ...
```

---

## 6. Directory layout

Tier folders, mirroring the unit-tests branch:

```
services/<svc>/tests/
  __init__.py
  unit/                              # tier 1
  service/                           # tier 2 (this tier)
    __init__.py
    test_<thing>.py
  integration/                       # tier 3
  acceptance/                        # tier 4
```

Tier marker is auto-applied based on which tier directory the test is in (see §8). Filenames are plain `test_*.py` — no `_service` suffix.

Component subfolders are fine when a tier folder gets crowded:

```
services/global_chat/tests/service/
  test_router.py
  test_planner.py
  planner/
    test_subagent_passthrough.py
    test_search_documentation_stub.py
```

Cross-service planner-chain tests live under `services/global_chat/tests/service/` since `global_chat` owns the planner.

---

## 7. Shared helpers in `services/testing/`

`services/testing/` is on the import path via `pythonpath = ["services"]` (same as how services do `from util import …`). No path-munging hacks.

```
services/testing/
  __init__.py
  README.md
  anthropic_mock.py     # MockAnthropic + tool_use helper
  fixtures.py           # pytest fixtures + payload builders + env setup
  yaml_assertions.py    # YAML structural helpers (unit-tier safe; owned by unit tier)
```

`fixtures.py` holds:

- `make_global_chat_payload`, `make_workflow_chat_payload`, `make_job_chat_payload`
- Pytest fixtures: `mock_anthropic`, `test_hooks_factory`, `fake_api_key`

Dummy env vars (Anthropic / OpenAI / Pinecone / Langfuse keys) are set inline in the root `conftest.py` at import time, before any service module loads — `setdefault` so real keys (for integration / acceptance) win.

---

## 8. Pytest configuration

Owned by the unit tier in PR #1. Service tier inherits everything; this section just lists what it relies on.

```toml
[tool.pytest.ini_options]
pythonpath = ["services"]
testpaths = [
    "services/global_chat/tests",
    "services/workflow_chat/tests",
    "services/job_chat/tests",
    "services/tools",
]
python_files = ["test_*.py"]
markers = [
  "unit: ...",
  "service: main() tests with mocked LLM HTTP client",
  "integration: ...",
  "acceptance: ...",
]
addopts = ["--strict-markers", "--strict-config", "-ra", "--tb=short"]
```

The root `conftest.py` walks `item.path.parts` looking for `unit`/`service`/`integration`/`acceptance` — directory IS the marker. Authors don't decorate manually.

---

## 9. CI integration

Service runs in the same `tests.yaml` workflow as unit, via `pytest -m "unit or service"`. No secrets on this job (invariant). See overview §6.

---

## 10. Migration recipe for existing `pass_fail` tests

1. **Classify.** Content-sensitive (`"response mentions Salesforce"`) → integration / acceptance. Structural (`"workflow_yaml has 2 jobs"`) → service.
2. **Replace the call site.** Swap `subprocess.run([..., "entry.py", ...])` for `from <svc>.<svc> import main; main(payload, test_hooks)`.
3. **Build the mock.** Register `set_response(pattern, response)` pairs covering each Anthropic call in the path under test.
4. **Assert on structure + breadcrumbs.** Replace content asserts with routing / shape asserts.
5. **Delete the old test** once stable.

Expect ~50–70% of `pass_fail` tests to become service tests; the rest stay in integration.

---

## 11. Production-code edits (summary)

| File | Edit |
|------|------|
| `services/global_chat/global_chat.py` | `main(data_dict, test_hooks=None)`; thread through |
| `services/workflow_chat/workflow_chat.py` | same |
| `services/job_chat/job_chat.py` | same |
| `services/global_chat/router.py` | accept `test_hooks` in `__init__`; pass into sub-agent calls |
| `services/global_chat/planner.py` | accept `test_hooks`; use in `_execute_tool`; thread into subagent_caller |
| `services/global_chat/subagent_caller.py` | accept `test_hooks`; pass to sub-agent `main()` |
| `services/util.py` | add `build_anthropic_client()` and `record_tool_call()` |

Backward-compatible defaults everywhere. `test_hooks is None` ⇒ existing behaviour, byte-for-byte.

---

## 12. Extensibility

**New sub-agent:**

1. `services/my_new_agent/my_new_agent.py` with `def main(data, test_hooks=None)`.
2. Every `Anthropic(...)` site uses `build_anthropic_client(api_key, test_hooks)`.
3. Thread `test_hooks` through internal calls.
4. Add `services/my_new_agent/tests/service/test_*.py`.

**New tool in the planner:**

1. Append to `services/global_chat/tools/tool_definitions.py`.
2. Dispatch branch in `planner._execute_tool` calls `record_tool_call(test_hooks, ...)`.
3. Write service tests.

Pattern: **one arg, one call to `record_tool_call`, one test**. No framework changes.

---

## 13. Deliberately deferred

- Sub-agent stub registry — sub-agents run under the shared mock client by default.
- `seed`, `disable_langfuse`, `scratch` keys — add when a test fails without them.
- Streaming mock support — covered by integration tier.

---

## 14. Targets for this tier

- **API key threading** — payload `api_key` ends up in `mock.last_request.headers["x-api-key"]`.
- **Cache-control regression** — assert on outbound request body via `json.loads(mock.last_request.content)`.
- **Context-management beta** — header + `context_management` field on every call.
- **History round-trip** — returned `history` equals input + this turn's user/assistant messages.
- **`AdaptorSpecifier` propagation** — payload `context.adaptor` shows up in the prompt.
- **Retry loops** — `workflow_chat` retries once on YAML parse failure; script invalid-then-valid and assert count.
- **Negative paths** — missing `content` → `ApolloError(400)`; malformed tool-use response → graceful fallback.

---

## Summary

`test_hooks` second arg on `main()` + `build_anthropic_client(api_key, test_hooks)` and `record_tool_call(test_hooks, entry)` in `services/util.py` + `MockAnthropic` (regex → response pairs, `AssertionError` on no match) in `services/testing/anthropic_mock.py` + three `test_hooks` keys (`anthropic_http_client`, `tool_calls`, `tool_stubs`). Tier folders auto-mark by directory. Streaming and sub-agent stubs deferred.
