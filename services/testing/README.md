# services/testing

Shared helpers for the test suite.

This directory is on the Python path via `pyproject.toml`
(`pythonpath = ["services"]`), so tests import as
`from testing.yaml_assertions import assert_yaml_equal_except`.

## Modules

- `yaml_assertions.py` — pure-function YAML structural assertions, safe for
  every tier (unit included).
- `judge.py` — LLM-as-judge helper for acceptance tests. Evaluates chat-service
  responses against natural-language criteria. Loads universal rules from
  `judge_rules.md` at evaluation time. Defaults to `CLAUDE_SONNET` from
  `services/models.py`.
- `judge_rules.md` — universal rules prepended to every acceptance judge
  evaluation. Edit this file to add project-wide standards (voice, style,
  refusal handling, etc.). One rule per bullet. Empty file = no universal rules.
- `spec_parser.py` — parses acceptance test markdown specs
  (`services/<svc>/tests/acceptance/*.md`) into `Spec` dataclasses.
- `spec_collector.py` — pytest plugin (registered via `pytest_plugins` in the
  repo-root `conftest.py`). Turns each MD spec into a pytest item that builds
  the service payload, calls the service via `ApolloClient`, and runs the judge.
- `apollo_client.py` — `ApolloClient` for dispatching to a chat service.
  Currently a subprocess-based stub; the integration tier will replace its
  internals with a real HTTP client (same `.call()` signature, no test changes).
- `fixtures.py` — pytest fixtures (`apollo_client`). Registered via
  `pytest_plugins = ["testing.fixtures"]` in the repo-root `conftest.py`.

## Why under `services/` and not a top-level `tests/`?

Imports across the codebase resolve relative to `services/` (see
`CLAUDE.md` → "Python Import Patterns"). Putting helpers here means tests
import without path-munging hacks, the same way services do `from util
import …`.

The Bun service auto-discovery in `platform/src/util/describe-modules.ts`
skips this directory because it has no `testing.py` index file.
