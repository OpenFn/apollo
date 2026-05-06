# services/testing

Shared helpers for the test suite.

This directory is on the Python path via `pyproject.toml`
(`pythonpath = ["services"]`), so tests import as
`from testing.anthropic_mock import MockAnthropic`.

## Modules

- `anthropic_mock.py` — `MockAnthropic` (httpx.MockTransport-backed) and the
  `tool_use(...)` content-block helper. Service tier.
- `fixtures.py` — pytest fixtures (`mock_anthropic`, `test_hooks_factory`,
  `fake_api_key`), payload builders, and `set_default_test_env`.
- `yaml_assertions.py` — pure-function YAML structural assertions, safe for
  every tier (unit included). Owned by the unit tier.

## Why under `services/` and not a top-level `tests/`?

Imports across the codebase resolve relative to `services/` (see
`CLAUDE.md` → "Python Import Patterns"). Putting helpers here means tests
import without path-munging hacks, the same way services do `from util
import …`.

The Bun service auto-discovery in `platform/src/util/describe-modules.ts`
skips this directory because it has no `testing.py` index file.
