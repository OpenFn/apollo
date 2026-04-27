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

### 2.1 Signature change

```python
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict: ...
```

`entry.py` keeps calling `m.main(data)` with one positional arg — the HTTP path never sees `test_hooks`. `test_hooks` is a test-only affordance.

### 2.2 The `test_hooks` dict — minimum viable shape

Plain Python `dict`. No `TypedDict`, no pydantic model — just a dict with documented keys. The recognised keys are documented as a docstring in `testing/anthropic_mock.py`:

```python
# testing/anthropic_mock.py
"""
The `test_hooks` dict accepts (all optional; all default to absent):

- "anthropic_http_client": an httpx.Client backed by httpx.MockTransport.
  When present, threaded into every Anthropic(...) constructor site.
- "tool_calls": a list[dict] the test allocates. Production code appends
  breadcrumbs via record_tool_call(test_hooks, entry).
- "tool_stubs": dict[str, Callable] keyed by tool name. When the planner
  dispatches a tool, if a stub exists for that name, the stub is called
  with the tool input and its return value used as the tool result. Today
  only used for "search_documentation" — see §5.
"""
```

Start with three keys. Add more only when a concrete test can't be written without one. Things intentionally left out until needed:

- Sub-agent stub registry. Default behaviour: the sub-agent's `main()` runs under the same mock HTTP client — that's usually what a test wants. A stub registry (`test_hooks["subagent_stubs"]`) can be added if a test needs to bypass the sub-agent's logic entirely.
- `seed`, `disable_langfuse`, `scratch`. Add when a test fails without them.

### 2.3 Threading `test_hooks` through

Each chat service's `main()` passes `test_hooks` into the agent / client constructors it creates. Everywhere that currently calls `Anthropic(api_key=...)` swaps to `build_anthropic_client(api_key, test_hooks)` (new factory — see §3).

Sites that change:

- `services/job_chat/job_chat.py` — `AnthropicClient.__init__`.
- `services/workflow_chat/workflow_chat.py` — `AnthropicClient.__init__`.
- `services/global_chat/router.py` — `RouterAgent.__init__`.
- `services/global_chat/planner.py` — `PlannerAgent.__init__`.
- `services/global_chat/subagent_caller.py` — accepts `test_hooks` and forwards to sub-agent `main()` calls.

Production behaviour when `test_hooks is None` is byte-identical to today. Every new kwarg defaults to `None`.

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

### 3.2 `MockAnthropic` in `testing/anthropic_mock.py`

`MockAnthropic` is a thin wrapper over `httpx.MockTransport`. Tests register regex → response pairs; on each Anthropic request the mock matches the latest user message text against registered patterns and returns the first match. No new runtime dep — `httpx.MockTransport` is built into httpx, which is already in `poetry.lock`.

```python
class MockAnthropic:
    """Mock Anthropic API backed by httpx.MockTransport.

    Tests register regex → response pairs. Each request is matched against
    the latest user message text (including tool_result content); the first
    matching pattern wins. No match raises AssertionError.

    Usage:
        mock = MockAnthropic()
        mock.set_response(r"haiku", "sure, here's a haiku")
        mock.set_response(r"create workflow", tool_use("call_workflow_agent", {...}))

        test_hooks = test_hooks_factory(anthropic=mock)
        main(payload, test_hooks)

        assert mock.last_request.headers["x-api-key"] == "sk-test"
    """

    def __init__(self):
        self._responses: list[tuple[re.Pattern, str | list[dict]]] = []
        self.requests: list[httpx.Request] = []

    def set_response(self, pattern: str, response: str | list[dict]) -> None:
        """Register a response for any request whose latest user message
        text matches `pattern`. `response` is either:
        - str: returned as a single text content block.
        - list[dict]: returned as content blocks (use for tool_use, mixed).
        """
        self._responses.append((re.compile(pattern), response))

    @property
    def httpx_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        user_text = _latest_user_text(body.get("messages", []))
        for pattern, resp in self._responses:
            if pattern.search(user_text):
                return httpx.Response(200, json=_build_message_body(resp))
        raise AssertionError(
            f"MockAnthropic: no pattern matched user message {user_text!r}. "
            f"Registered patterns: {[p.pattern for p, _ in self._responses]}"
        )


def tool_use(name: str, input: dict, id: str = "toolu_test") -> list[dict]:
    """Build a single tool_use content block for `set_response`."""
    return [{"type": "tool_use", "id": id, "name": name, "input": input}]
```

Two private helpers in the same file:

- `_latest_user_text(messages)` walks `messages` in reverse, takes the last `role=user` message, and concatenates its `text` blocks plus any `tool_result` content. Matching against `tool_result` text is what makes the planner's internal loop work — see §3.3.
- `_build_message_body(response)` wraps a string in `[{"type": "text", "text": ...}]` (or passes a list through), then assembles the standard Anthropic message envelope: `id`, `type`, `role: "assistant"`, `model`, `content`, `stop_reason`, `stop_sequence`, `usage`.

Design choices worth knowing:

- **First-match-wins.** Order specific patterns before general ones.
- **Loud no-match.** Raises `AssertionError` with the unmatched text and the list of registered patterns. Beats silent fallbacks that mask test drift.
- **Captured requests.** `mock.requests` (list) and `mock.last_request` for assertions on outbound headers, body shape, system prompt, `cache_control`, beta headers, history round-trip.

Tool-call breadcrumbs (`record_tool_call`) live in the same file — see §4.

### 3.3 The planner's internal loop

`main()` is one user turn, but the planner agent internally calls Anthropic multiple times within that turn — once per round of the tool-use loop (`call → tool_use → run tool → call with tool_result → ...` until `end_turn`). The regex matcher handles this naturally because each round has different content in the latest user message:

```python
def test_planner_calls_workflow_then_job_agents(test_hooks_factory):
    mock = MockAnthropic()
    mock.set_response(r"create a workflow",
                      tool_use("call_workflow_agent", {"message": "create workflow"}))
    mock.set_response(r"workflow created",
                      tool_use("call_job_code_agent", {"message": "code", "job_key": "fetch"}))
    mock.set_response(r"code generated", "all done")

    test_hooks = test_hooks_factory(anthropic=mock)
    main(make_global_chat_payload("create a workflow"), test_hooks)

    assert [c["tool"] for c in test_hooks["tool_calls"]] == [
        "call_workflow_agent", "call_job_code_agent",
    ]
```

- Round 1: latest user message = the user's prompt → matches `r"create a workflow"`, returns the first `tool_use`.
- Round 2: latest user message = the `tool_result` from `call_workflow_agent` → matches `r"workflow created"`, returns the next `tool_use`.
- Round 3: latest user message = the `tool_result` from `call_job_code_agent` → matches `r"code generated"`, returns the final text.

When a sub-agent (`workflow_chat`, `job_chat`) gets invoked inside this loop, its own `main()` runs under the *same* mock client. Tests register regexes covering both the parent's and the child's expected user messages on one mock — no sub-agent stub registry needed.

### 3.4 Streaming (deferred)

Streaming endpoints (`/services/<svc>/stream`, `/services/<svc>` WS) emit Anthropic-formatted SSE events through `bridge.ts` (`StreamManager` in `services/streaming_util.py`). Detailed mock support — likely a `set_stream_response(pattern, events)` method or a sibling `MockAnthropicStream` class — is out of scope for this section. Defer until the first service test for a streaming code path actually needs it; meanwhile the integration tier covers stream behaviour against the real bun server.

---

## 4. Tool-call breadcrumbs (`test_hooks["tool_calls"]`)

`test_hooks["tool_calls"]` is a list the test allocates and production code appends to. One helper in `testing/anthropic_mock.py`:

```python
def record_tool_call(test_hooks: Optional[dict], entry: dict) -> None:
    if test_hooks is None:
        return
    crumbs = test_hooks.get("tool_calls")
    if crumbs is not None:
        crumbs.append(entry)
```

Dispatch sites (`planner._execute_tool`, `router.route_and_execute`) call `record_tool_call(test_hooks, {"tool": ..., "input": ...})`. Two dict lookups per call when `test_hooks is None` — negligible.

Tests read:

```python
assert [c["tool"] for c in test_hooks["tool_calls"]] == ["router_decision", "call_workflow_agent"]
```

---

## 5. Tool stubs (`test_hooks["tool_stubs"]`)

Most planner tools don't need stubbing. `call_workflow_agent` and `call_job_code_agent` inherit `test_hooks` and run the sub-agent's own mocked `main()`. `inspect_job_code` is pure local code with no network. The one tool that does need stubbing is **`search_documentation`** — without a stub it would hit Pinecone (vector store) and OpenAI (embeddings) on every service test.

Production change in `services/global_chat/planner.py::_execute_tool` — one if/else at the top of the dispatch:

```python
stub = (self._test_hooks or {}).get("tool_stubs", {}).get(tool_use_block.name)
if stub is not None:
    tool_result = stub(tool_use_block.input)
else:
    # original dispatch by name follows
    ...
```

Test usage:

```python
test_hooks = {
    "anthropic_http_client": mock.httpx_client,
    "tool_calls": [],
    "tool_stubs": {
        "search_documentation": lambda tool_input: "Cron triggers run on a schedule...",
    },
}
result = main(payload, test_hooks)
```

The stub returns whatever shape the real tool returns (here a string — the planner feeds it back into the next Anthropic call).

A `build_search_documentation_stub(docs=[...])` helper in `testing/anthropic_mock.py` can emerge once a second test reuses the same shape — not preemptively.

---

## 6. Directory layout

```
services/<svc>/tests/
  __init__.py
  conftest.py                       # re-exports shared fixtures; auto-marks by filename suffix
  test_<module>_unit.py             # tier 1 (unit-tests-architect)
  test_<module>_service.py          # tier 2 (this tier)
  fixtures/                         # per-service fixture data (optional)
```

Test filenames this tier will add (illustrative, not exhaustive):

- `services/global_chat/tests/test_router_service.py` — router decisions by intent.
- `services/global_chat/tests/test_planner_service.py` — tool dispatch order, test_hooks propagation.
- `services/global_chat/tests/test_subagent_passthrough_service.py` — global → workflow / job wiring.
- `services/workflow_chat/tests/test_workflow_chat_service.py` — YAML extraction, retry loop, streaming events.
- `services/job_chat/tests/test_job_chat_service.py` — RAG injection (with stubbed retriever), suggest-code response shape, page-prefix detection, error-correction loop.

Cross-service end-to-end flow tests (planner chain over mocks) also live under `services/global_chat/tests/` since `global_chat` owns the planner.

---

## 7. Shared helpers in `testing/`

```
testing/
  __init__.py
  anthropic_mock.py      # MockAnthropic + tool_use helper, test_hooks-keys docstring, record_tool_call
  fixtures.py            # pytest fixtures + YAML assertion helpers + payload builders + loaders
  fixtures/
    workflows/*.yaml
    histories/*.json
```

`fixtures.py` is the flat home for:

- `make_global_chat_payload`, `make_workflow_chat_payload`, `make_job_chat_payload`.
- `get_workflow_yaml_attachment`, `get_suggested_code_attachment`, `get_usage`.
- `assert_yaml_has_ids`, `assert_yaml_jobs_have_body`, `assert_yaml_equal_except`, `path_matches`, `assert_no_special_chars`.
- Pytest fixtures: `mock_anthropic`, `test_hooks_factory`, `fake_api_key`, `sample_workflow_yaml`.
- `set_unit_test_env` (dummy keys, disable langfuse/sentry).
- `load_fixture_json`, `load_fixture_yaml`.

One file until it gets unwieldy (~500 lines). Split then, not pre-emptively.

Key fixture:

```python
@pytest.fixture
def test_hooks_factory():
    def _factory(*, anthropic=None, **overrides):
        opts = {"tool_calls": []}
        if anthropic is not None:
            opts["anthropic_http_client"] = anthropic.httpx_client
        opts.update(overrides)
        return opts
    return _factory
```

Per-service `conftest.py` just exposes `pytest_plugins = ["testing.fixtures"]` (inherited from root) plus any per-service niche fixtures.

---

## 8. Pytest configuration

Owned initially by this tier in PR #1 (bootstrap). See overview §5 for the full block. Relevant keys:

```toml
[tool.pytest.ini_options]
pythonpath = ["services", "."]
testpaths = ["services"]
python_files = ["test_*.py"]
markers = [
  "unit: ...",
  "service: main() tests with mocked LLM HTTP client",
  "integration: ...",
  "acceptance: ...",
]
addopts = ["-ra"]
```

Markers applied by filename suffix in the root `apollo/conftest.py` — authors don't decorate manually.

---

## 9. CI integration

Service runs in the same `tests.yaml` workflow as unit, via `pytest -m "unit or service"`. No secrets on this job (invariant). See overview §6.

---

## 10. Migration recipe for existing `pass_fail` tests

1. **Classify the assertion.** Content-sensitive (`"response mentions Salesforce"`) → integration or acceptance. Structural (`"workflow_yaml has 2 jobs"`) → service (with a canned mock producing that structure).
2. **Replace the call site.** Swap `subprocess.run([..., "entry.py", ...])` for `from <svc>.<svc> import main; main(payload, test_hooks)`.
3. **Build the mock.** Register one or more `set_response(pattern, response)` pairs on `MockAnthropic` so each Anthropic call in the path under test gets a matching canned response.
4. **Assert on structure + breadcrumbs.** Replace content asserts with routing / shape asserts; keep content in acceptance.
5. **Delete the old test** once the new one is stable.

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
| `services/util.py` | add `build_anthropic_client()` |

Everywhere: backward-compatible defaults. `test_hooks is None` ⇒ existing behaviour, byte-for-byte.

---

## 12. Extensibility — new sub-agent or tool

**New sub-agent:**

1. `services/my_new_agent/my_new_agent.py` with `def main(data, test_hooks=None)`.
2. Every `Anthropic(...)` site uses `build_anthropic_client(api_key, test_hooks)`.
3. Thread `test_hooks` through internal calls.
4. Add `services/my_new_agent/tests/test_*_service.py`. Conftest auto-inherits.

**New tool in the planner:**

1. Append to `services/global_chat/tools/tool_definitions.py`.
2. Dispatch branch in `planner._execute_tool` calls `record_tool_call(test_hooks, ...)`.
3. Write service tests.

Pattern: **one arg, one call to `record_tool_call`, one test**. No framework changes.

---

## 13. What this tier deliberately does NOT do

- **No sub-agent stub registry on day one.** Default behaviour (sub-agent runs under shared mock client) is what tests usually want.
- **No `test_hooks["seed"]` / `["disable_langfuse"]` / `["scratch"]`.** Add when a test fails without them.
- **No `pytest-asyncio`, `pytest-randomly`, or other dev deps.** Add when needed.
- **No frozen public API contract between tiers.** Shared helpers live in one package; rename when the signature improves.

---

## 14. What else belongs in this tier

Good service-test targets:

- **API key threading** — payload `api_key` ends up in `mock.last_request.headers["x-api-key"]`; absent → env var is used.
- **Cache-control regression** — planner system prompt has `cache_control: {"type": "ephemeral"}`; assert on outbound request body via `json.loads(mock.last_request.content)` (httpx `Request.content` is bytes — there's no `.json` accessor on the request side).
- **Context-management beta** — planner sets `context-management-2025-06-27` header and `context_management` field on every call.
- **History round-trip** — returned `history` equals input + this turn's user/assistant messages.
- **`AdaptorSpecifier` propagation** — payload `context.adaptor = "@openfn/language-http@3.1.11"` shows up in the prompt.
- **Retry loops** — `workflow_chat` retries once on YAML parse failure; script invalid-then-valid and assert count.
- **Negative paths** — missing `content` → `ApolloError(400)`; malformed tool-use response → graceful fallback.

---

## Summary

`test_hooks` second arg on `main()` + `build_anthropic_client(api_key, test_hooks)` factory + `MockAnthropic` (regex → response pairs, `AssertionError` on no match) with a `tool_use(...)` helper for tool-use content blocks + three `test_hooks` keys (`anthropic_http_client`, `tool_calls`, `tool_stubs` — the last only used for `search_documentation` today). One mock file in `testing/`, filename-suffix markers, shared workflow with the unit tier. Streaming and any sub-agent stub infrastructure are deferred until a real test needs them.
