# Apollo Testing Architecture — Layer 1: Unit Tests (Simplified)

**Scope:** `services/global_chat/`, `services/workflow_chat/`, `services/job_chat/`, their tools, and any future sub-agent / tool service.

---

## 1. What qualifies as a unit test in Apollo

A test is a unit test iff ALL of:

1. Exercises **exactly one function, method, or pure class behaviour**.
2. **Zero I/O** — no network (Anthropic, Pinecone, Langfuse export, Sentry), no subprocess, no DB, no file writes outside `tmp_path`.
3. **Zero LLM calls**, not even through a mock HTTP client. If the test needs a mocked Anthropic response to make sense, it's a service test.
4. **Deterministic and fast** — target <50 ms per test; whole unit suite <15 s.
5. **Free** — no API keys required.

Tests that don't meet all five get moved to service or integration — see §7.

---

## 2. Directory and file layout

Per-service: one flat `tests/` folder, filenames suffixed by tier.

```
services/<svc>/tests/
  __init__.py
  conftest.py                        # thin — re-exports shared fixtures; auto-applies tier marker by filename suffix
  test_<module>_unit.py              # ← this tier
  test_<module>_service.py           # tier 2
  fixtures/                          # optional; static JSON/YAML sample inputs (per-service only)
```

Cross-service util tests (`services/util.py` — `AdaptorSpecifier`, `DictObj`, `sum_usage`, `add_page_prefix`) live under `services/tests/test_util_unit.py`.

**Why suffix + auto-marker, not subdirs?** While each service has <20 test files, subdirs add bureaucracy for no gain. Tier marker is applied by filename suffix in the per-service conftest. If a service grows past ~30 test files, promoting to `tests/unit/` + `tests/service/` subdirs is a mechanical rename.

---

## 3. Shared helper package: `services/_testing/`

Leading underscore is required — `platform/src/util/describe-modules.ts` auto-mounts any directory under `services/` whose name doesn't start with `_`.

```
services/_testing/
  __init__.py
  anthropic_mock.py       # owned by service tier; unit tier does not import
  fixtures.py             # pytest fixtures: sample payloads, fake api keys, yaml-assertion helpers
  fixtures/               # sample YAML / JSON shared across services
    workflows/*.yaml
    histories/*.json
```

Unit-tier import rules:

- ✅ Import from `services/_testing/fixtures.py` — pytest fixtures, YAML assertion helpers, payload builders, fixture loaders.
- ❌ Do not import from `services/_testing/anthropic_mock.py` — that's the service tier's territory.

`services/_testing/fixtures.py` owns (same module, flat — split into files only when this one grows past ~500 lines):

- Pytest fixtures (`sample_workflow_yaml`, `sample_<svc>_chat_payload`, `fake_api_key`, `anthropic_client_no_network`).
- YAML assertion helpers migrated from the currently-duplicated `services/global_chat/tests/test_utils.py` and `services/workflow_chat/tests/test_utils.py` (`path_matches`, `assert_yaml_equal_except`, `assert_yaml_section_contains_all`, `assert_yaml_has_ids`, `assert_yaml_jobs_have_body`, `assert_no_special_chars`).
- Payload builders (`make_<svc>_chat_payload`) — shared with integration tier.
- Fixture loaders (`load_fixture_json`, `load_fixture_yaml`).
- `set_unit_test_env()` — dummy keys, disable langfuse/sentry.

These are pure functions, so they themselves deserve unit tests in `services/tests/test_fixtures_unit.py`.

---

## 4. Test runner and configuration

pytest. Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
minversion = "8.0"
pythonpath = ["services"]
testpaths = ["services", "tests"]
python_files = ["test_*.py"]
markers = [
  "unit: fast, isolated, no I/O, no LLM, no network",
  "service: main() with mocked anthropic HTTP client",
  "integration: real LLM via bun server",
  "acceptance: LLM-judged quality/voice tests",
]
addopts = ["-ra"]
```

`pythonpath = ["services"]` kills the `sys.path.insert(...)` boilerplate at the top of every existing test file.

Commands:

```bash
poetry run pytest -m unit
poetry run pytest services/global_chat/tests -m unit
poetry run pytest services/workflow_chat/tests/test_workflow_chat_functions_unit.py
```

TypeScript platform tests continue to use `bun:test`. Unchanged.

---

## 5. Conftest strategy

Two levels:

### 5.1 Root: `services/conftest.py`

- Calls `services._testing.fixtures.set_unit_test_env()` at import time.
- Exposes `pytest_plugins = ["services._testing.fixtures"]` so shared fixtures are globally available.

### 5.2 Per-service: `services/<svc>/tests/conftest.py`

- Service-specific fixtures (e.g. a `global_chat_router_decision` factory). Usually <30 lines.
- Auto-applies the tier marker by filename suffix:

  ```python
  def pytest_collection_modifyitems(config, items):
      for item in items:
          name = item.fspath.basename
          if name.endswith("_unit.py"):
              item.add_marker(pytest.mark.unit)
          elif name.endswith("_service.py"):
              item.add_marker(pytest.mark.service)
  ```

Same loop can live in the root `services/conftest.py` instead — one copy rather than per-service. Minor detail for implementation.

---

## 6. CI integration

Unit and service both run in `.github/workflows/tests.yaml` under one job with `-m "unit or service"`. Triggers on every push / PR. No secrets. 10-minute timeout. See overview §6.

Coverage: generate `--cov=services --cov-report=xml` and upload as artifact for visibility; no threshold gate.

---

## 7. Migration path for existing tests

- `services/workflow_chat/tests/test_functions.py` — all eight tests are already unit-shaped. Rename to `test_workflow_chat_functions_unit.py`, delete `sys.path.insert(...)`, replace local `client` fixture with `anthropic_client_no_network`. No assertion changes.
- `services/job_chat/tests/test_functions.py` — misclassified. `test_generate_system_message_loads_adaptor_docs_when_missing` hits Postgres → integration. `test_generate_queries_returns_valid_structure` hits real Anthropic → service (with mocked client) or integration. `test_search_docs_returns_general_docs_only` hits Pinecone → integration. A new `test_prompt_unit.py` covers the pure helpers (`build_prompt`, `build_error_correction_prompt`, `extract_page_prefix_from_last_turn`).
- `services/global_chat/tests/test_utils.py` + `services/workflow_chat/tests/test_utils.py` — YAML helpers migrate to `services/_testing/fixtures.py`. The `call_<svc>_service` subprocess helpers are replaced by the integration tier's `ApolloClient`. Old files are deleted after all callers are updated.
- `*_pass_fail.py`, `*_qualitative.py`, `*_langfuse_tracing.py`, `*_adaptor_version_passthrough.py`, `*_planner_*.py`, `*_good_morning_*.py` — owned by service/integration/acceptance tiers.

**Migration order:**

1. Create `services/_testing/` skeleton + root `services/conftest.py` (empty fixtures — just env guard + network block).
2. Add `[tool.pytest.ini_options]` to pyproject.
3. Migrate `workflow_chat/tests/test_functions.py` (smallest, cleanest — the worked example).
4. Wire `.github/workflows/tests.yaml` with `-m unit` initially.
5. Only then start adding net-new unit tests for `yaml_utils.py`, `config_loader.py`, `tool_definitions.py`, etc.

---

## 8. Extensibility — new sub-agent or tool

A new service `services/my_new_agent/`:

1. Create `services/my_new_agent/tests/` with a conftest (copy the auto-marker loop).
2. Add `test_<module>_unit.py` files.

A new tool in `services/<svc>/tools/`:

1. Add `services/<svc>/tests/test_<tool>_unit.py`. Tool schema dicts are ideal targets — assert shape, required keys, JSON-schema validity.

No pyproject, CI, or shared-package edits required.

---

## 9. Boundaries with other tiers

- **Unit stops / service begins:** the moment a test needs `main()` to run, or needs to verify "logs appended to prompt" / "api key ended up in headers" / "router picked workflow_agent when given X", it's a service test.
- **Unit stops / integration begins:** if a test needs a live Anthropic response (even for shape), it's integration. If it needs the bun server, it's integration.
- **Unit stops / acceptance begins:** no overlap — acceptance is about answer quality, unit is about code correctness.

---

## 10. Things deliberately NOT done

- No per-tier subdirectories per service.
- No separate `env.py` / `loaders.py` / `yaml_assertions.py` modules in `_testing/` — one `fixtures.py` until a concrete split is warranted.
- No coverage gates.
- No property-based testing (Hypothesis) in the initial plan — add a `strategies.py` module when the need arises.
- No pytest plugin dev dep beyond what's already in poetry.lock.

---

## Summary

Unit layer is small, boring, and fast. One flat `tests/` folder per service with filename-suffixed tiers, one `services/_testing/` package with three files, dummy env vars in the root conftest, CI on every push with no secrets. Adding a unit test for a new function is a one-line import and a `def test_...`.
