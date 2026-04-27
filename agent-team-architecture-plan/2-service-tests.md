# Section 2 — Service Tests Architecture (Simplified)

> Scope: `services/global_chat/`, `services/workflow_chat/`,
> `services/job_chat/`, and the tools / sub-agents they invoke.

---

## 1. Naming and position

**Service tests** — direct calls to `main()` with Anthropic HTTP calls mocked.
One rung above unit, one below integration.

| Tier        | Scope                   | LLM calls  | HTTP layer             | Cost     | Runs on PR push  |
| ----------- | ----------------------- | ---------- | ---------------------- | -------- | ---------------- |
| unit        | single function         | no         | no                     | free     | yes              |
| **service** | **`main()` end-to-end** | **mocked** | **no (direct python)** | **free** | **yes**          |
| integration | `main()` via server     | real       | yes                    | $$       | manual / label   |
| acceptance  | behaviour spec          | real       | yes                    | $$$      | nightly / manual |

Service tests verify _logic and information flow_: payload validation, routing,
prompt assembly, tool-call orchestration, sub-agent invocation, history/usage
aggregation, error paths, headers, api_key passthrough. They do **not** verify
model quality.

---

## 2. The `test_hooks` second argument

### 2.1 Signature change

```python
def main(data_dict: dict, test_hooks: Optional[dict] = None) -> dict: ...
```

`entry.py` keeps calling `m.main(data)` with one positional arg — the HTTP path
never sees `test_hooks`. `test_hooks` is a test-only affordance.

### 2.2 The `test_hooks` dict — minimum viable shape

i wouldnt mind thinking through the mocks and options we need a bit more! eg
openai embedddings

Plain Python `dict`. No `TypedDict`, no pydantic model — just a dict with
documented keys. The recognised keys are documented as a docstring in
`services/_testing/anthropic_mock.py`:

```python
# services/_testing/anthropic_mock.py
"""
The `test_hooks` dict accepts (all optional; all default to absent):

- "anthropic_http_client": an httpx.Client backed by httpx.MockTransport.
  When present, threaded into every Anthropic(...) constructor site.
- "tool_calls": a list[dict] the test allocates. Production code appends
  breadcrumbs via record_tool_call(test_hooks, entry).
"""
```

Start with two keys. Add more only when a concrete test can't be written without
one. Things intentionally left out until needed:

- Sub-agent stub registry. Default behaviour: the sub-agent's `main()` runs
  under the same mock HTTP client — that's usually what a test wants. A stub
  registry (`test_hooks["subagentStubs"]`) can be added if a test needs to
  bypass the sub-agent's logic entirely.
- Tool stub registry. Same logic — add only when a test needs to short-circuit a
  tool without exercising its real code path.
- `seed`, `disableLangfuse`, `scratch`. Add when a test fails without them.

### 2.3 Threading `test_hooks` through

Each chat service's `main()` passes `test_hooks` into the agent / client
constructors it creates. Everywhere that currently calls
`Anthropic(api_key=...)` swaps to `build_anthropic_client(api_key, test_hooks)`
(new factory — see §3).

Sites that change:

- `services/job_chat/job_chat.py` — `AnthropicClient.__init__`.
- `services/workflow_chat/workflow_chat.py` — `AnthropicClient.__init__`.
- `services/global_chat/router.py` — `RouterAgent.__init__`.
- `services/global_chat/planner.py` — `PlannerAgent.__init__`.
- `services/global_chat/subagent_caller.py` — accepts `test_hooks` and forwards
  to sub-agent `main()` calls.

Production behaviour when `test_hooks is None` is byte-identical to today. Every
new kwarg defaults to `None`.

---

## 3. Mock Anthropic HTTP client

### 3.1 Factory in `services/util.py`

this moves to top /lib

CAN WE SET TEST HOOK GLOBALLY? OR IN MODULE SCOPE?

```python
import test_hooks;

def build_anthropic_client(api_key: str) -> Anthropic:
    http_client = test_hooks.get("anthropicHttpClient")
    kwargs = {"api_key": api_key}
    if http_client is not None:
        logger.debug("Using mock anthropic client")
        kwargs["http_client"] = http_client
    return Anthropic(**kwargs)


# test.py
import test_hooks;

setTestHooks({... })

# job_chat.py
build_anthropic_client(args.api_key)
```

Every `AnthropicClient` / `RouterAgent` / `PlannerAgent` constructor swaps
`Anthropic(api_key=...)` for `build_anthropic_client(api_key, test_hooks)`.

### 3.2 `services/_testing/anthropic_mock.py`

Single file — `MockAnthropicClient` class, canned response-body builders,
docstring documenting recognised `test_hooks` keys, and the
`record_tool_call(test_hooks, entry)` helper. Split later if it grows unwieldy.

The `anthropic` Python SDK accepts a custom `http_client` — we build ours from
`httpx.MockTransport`:

```python
class MockAnthropicClient:
    """Thin wrapper over httpx.Client + httpx.MockTransport.

    Usage:
        mc = MockAnthropicClient.always(response=text_response("hello"))
        mc = MockAnthropicClient.script([resp1, resp2, resp3])   # multi-turn
        mc = MockAnthropicClient.streaming(events=[...])         # SSE

    After the call:
        mc.requests            # list[RecordedRequest]
        mc.last_request.json["messages"]
        mc.last_request.headers["x-api-key"]
    """
    @classmethod
    def always(cls, response) -> "MockAnthropicClient": ...
    @classmethod
    def script(cls, responses) -> "MockAnthropicClient": ...
    @classmethod
    def streaming(cls, events) -> "MockAnthropicClient": ...

    @property
    def httpx_client(self) -> httpx.Client: ...
    @property
    def requests(self) -> list[RecordedRequest]: ...
    @property
    def last_request(self) -> RecordedRequest: ...
```

Response-body builders in the same file:

- `text_response(text, model=..., usage=...)`
- `tool_use_response(tool_name, tool_input, tool_use_id="toolu_01")`
- `mixed_response(text, tool_uses=[...])`
- `router_decision_response(destination, confidence=4, job_key=None)`
- `stream_events(text="", tool_uses=None)`
- `usage_block(input_tokens=100, output_tokens=50, cache_creation=0, cache_read=0)`

No new runtime dep — `httpx.MockTransport` is built into httpx, which is already
in `poetry.lock`.

### 3.3 Scripted multi-turn example

```python
def test_planner_calls_workflow_then_job_agents(test_hooks_factory):
    mock = MockAnthropicClient.script([
        router_decision_response("planner", confidence=5),
        tool_use_response("call_workflow_agent", {"message": "create workflow"}),
        tool_use_response("call_job_code_agent", {"message": "code for step", "job_key": "fetch"}),
        text_response("All done."),
    ])
    test_hooks = test_hooks_factory(anthropic=mock)
    result = global_chat_main(make_global_chat_payload("create a workflow"), test_hooks)

    assert [c["tool"] for c in test_hooks["toolCalls"]] == [
        "router_decision", "call_workflow_agent", "call_job_code_agent",
    ]
```

When a test wants to bypass a sub-agent's real code, it scripts responses for
the planner's `/v1/messages` calls and lets the sub-agent's own `main()` run
under the same mock client. Stub registries aren't needed for the common case.

---

## 4. Tool-call breadcrumbs (`test_hooks["toolCalls"]`)

`test_hooks["toolCalls"]` is a list the test allocates and production code
appends to. One helper in `services/_testing/anthropic_mock.py`:

```python
def record_tool_call(test_hooks: Optional[dict], entry: dict) -> None:
    if test_hooks is None:
        return
    crumbs = test_hooks.get("toolCalls")
    if crumbs is not None:
        crumbs.append(entry)
```

Dispatch sites (`planner._execute_tool`, `router.route_and_execute`) call
`record_tool_call(test_hooks, {"tool": ..., "input": ...})`. Two dict lookups
per call when `test_hooks is None` — negligible.

Tests read:

```python
assert [c["tool"] for c in test_hooks["toolCalls"]] == ["router_decision", "call_workflow_agent"]
```

---

## 5. Directory layout

```
services/<svc>/tests/
  __init__.py
  conftest.py                       # re-exports shared fixtures; auto-marks by filename suffix
  test_<module>_unit.py             # tier 1 (unit-tests-architect)
  test_<module>_service.py          # tier 2 (this tier)
  fixtures/                         # per-service fixture data (optional)
```

Test filenames this tier will add (illustrative, not exhaustive):

- `services/global_chat/tests/test_router_service.py` — router decisions by
  intent.
- `services/global_chat/tests/test_planner_service.py` — tool dispatch order,
  test_hooks propagation.
- `services/global_chat/tests/test_subagent_passthrough_service.py` — global →
  workflow / job wiring.
- `services/workflow_chat/tests/test_workflow_chat_service.py` — YAML
  extraction, retry loop, streaming events.
- `services/job_chat/tests/test_job_chat_service.py` — RAG injection (with
  stubbed retriever), suggest-code response shape, page-prefix detection,
  error-correction loop.

Cross-service end-to-end flow tests (planner chain over mocks) also live under
`services/global_chat/tests/` since `global_chat` owns the planner.

---

## 6. Shared helpers in `services/_testing/`

```
services/_testing/
  __init__.py
  anthropic_mock.py      # MockAnthropicClient, response builders, test_hooks-keys docstring, record_tool_call
  fixtures.py            # pytest fixtures + YAML assertion helpers + payload builders + loaders
  fixtures/
    workflows/*.yaml
    histories/*.json
```

`fixtures.py` is the flat home for:

- `make_global_chat_payload`, `make_workflow_chat_payload`,
  `make_job_chat_payload`.
- `get_workflow_yaml_attachment`, `get_suggested_code_attachment`, `get_usage`.
- `assert_yaml_has_ids`, `assert_yaml_jobs_have_body`,
  `assert_yaml_equal_except`, `path_matches`, `assert_no_special_chars`.
- Pytest fixtures: `mock_anthropic`, `test_hooks_factory`, `fake_api_key`,
  `sample_workflow_yaml`, `anthropic_client_no_network`.
- `set_unit_test_env` (dummy keys, disable langfuse/sentry).
- `load_fixture_json`, `load_fixture_yaml`.

One file until it gets unwieldy (~500 lines). Split then, not pre-emptively.

Key fixture:

```python
@pytest.fixture
def test_hooks_factory():
    def _factory(*, anthropic=None, **overrides):
        opts = {"toolCalls": []}
        if anthropic is not None:
            opts["anthropicHttpClient"] = anthropic.httpx_client
        opts.update(overrides)
        return opts
    return _factory
```

Per-service `conftest.py` just exposes
`pytest_plugins = ["services._testing.fixtures"]` (inherited from root) plus any
per-service niche fixtures.

---

## 7. Pytest configuration

Owned initially by this tier in PR #1 (bootstrap). See overview §5 for the full
block. Relevant keys:

```toml
[tool.pytest.ini_options]
testpaths = ["services", "tests"]
python_files = ["test_*.py"]
markers = [
  "unit: ...",
  "service: main() tests with mocked LLM HTTP client",
  "integration: ...",
  "acceptance: ...",
]
addopts = ["-ra"]
```

Markers applied by filename suffix in the root `services/conftest.py` — authors
don't decorate manually.

---

## 8. CI integration

Service runs in the same `tests.yaml` workflow as unit, via
`pytest -m "unit or service"`. No secrets on this job (invariant). See overview
§6.

---

## 9. Migration recipe for existing `pass_fail` tests

1. **Classify the assertion.** Content-sensitive
   (`"response mentions Salesforce"`) → integration or acceptance. Structural
   (`"workflow_yaml has 2 jobs"`) → service (with a canned mock producing that
   structure).
2. **Replace the call site.** Swap `subprocess.run([..., "entry.py", ...])` for
   `from <svc>.<svc> import main; main(payload, test_hooks)`.
3. **Build the mock.** Hand-craft an Anthropic response fixture (or a script for
   planner multi-turn) that produces the shape under test.
4. **Assert on structure + breadcrumbs.** Replace content asserts with routing /
   shape asserts; keep content in acceptance.
5. **Delete the old test** once the new one is stable.

Expect ~50–70% of `pass_fail` tests to become service tests; the rest stay in
integration.

---

## 10. Production-code edits (summary)

| File                                      | Edit                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------ |
| `services/global_chat/global_chat.py`     | `main(data_dict, test_hooks=None)`; thread through                       |
| `services/workflow_chat/workflow_chat.py` | same                                                                     |
| `services/job_chat/job_chat.py`           | same                                                                     |
| `services/global_chat/router.py`          | accept `test_hooks` in `__init__`; pass into sub-agent calls             |
| `services/global_chat/planner.py`         | accept `test_hooks`; use in `_execute_tool`; thread into subagent_caller |
| `services/global_chat/subagent_caller.py` | accept `test_hooks`; pass to sub-agent `main()`                          |
| `services/util.py`                        | add `build_anthropic_client()`                                           |

Everywhere: backward-compatible defaults. `test_hooks is None` ⇒ existing
behaviour, byte-for-byte.

---

## 11. Extensibility — new sub-agent or tool

**New sub-agent:**

1. `services/my_new_agent/my_new_agent.py` with
   `def main(data, test_hooks=None)`.
2. Every `Anthropic(...)` site uses
   `build_anthropic_client(api_key, test_hooks)`.
3. Thread `test_hooks` through internal calls.
4. Add `services/my_new_agent/tests/test_*_service.py`. Conftest auto-inherits.

**New tool in the planner:**

1. Append to `services/global_chat/tools/tool_definitions.py`.
2. Dispatch branch in `planner._execute_tool` calls
   `record_tool_call(test_hooks, ...)`.
3. Write service tests.

Pattern: **one arg, one call to `record_tool_call`, one test**. No framework
changes.

---

## 12. What this tier deliberately does NOT do

- **No sub-agent stub registry on day one.** Default behaviour (sub-agent runs
  under shared mock client) is what tests usually want.
- **No tool stub registry on day one.** Same reason. Real tool code usually
  runs; when a tool hits Pinecone/Postgres, patch it in the test.
- **No `test_hooks["seed"]` / `["disableLangfuse"]` / `["scratch"]`.** Add when
  a test fails without them.
- **No `pytest-asyncio`, `pytest-randomly`, or other dev deps.** Add when
  needed.
- **No frozen public API contract between tiers.** Shared helpers live in one
  package; rename when the signature improves.

---

## 13. What else belongs in this tier

Good service-test targets:

- **API key threading** — payload `api_key` ends up in
  `mock.last_request.headers["x-api-key"]`; absent → env var is used.
- **Cache-control regression** — planner system prompt has
  `cache_control: {"type": "ephemeral"}`; assert on outbound request body.
- **Context-management beta** — planner sets `context-management-2025-06-27`
  header and `context_management` field on every call.
- **History round-trip** — returned `history` equals input + this turn's
  user/assistant messages.
- **`AdaptorSpecifier` propagation** — payload
  `context.adaptor = "@openfn/language-http@3.1.11"` shows up in the prompt.
- **Retry loops** — `workflow_chat` retries once on YAML parse failure; script
  invalid-then-valid and assert count.
- **Negative paths** — missing `content` → `ApolloError(400)`; malformed
  tool-use response → graceful fallback.

---

## Summary

`test_hooks` second arg on `main()` +
`build_anthropic_client(api_key, test_hooks)` factory + `MockAnthropicClient`
with `always`/`script`/`streaming` constructors + two optional `test_hooks` keys
(`anthropicHttpClient`, `toolCalls`). Three files in `services/_testing/`,
filename-suffix markers, shared workflow with the unit tier. Add sub-agent /
tool stub infrastructure the first time a test can't be written without it.
