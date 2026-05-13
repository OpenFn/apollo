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
  `judge_rules.md` at evaluation time.
- `judge_rules.md` — universal rules prepended to every acceptance judge
  evaluation. Edit this file to add project-wide standards (voice, style,
  refusal handling, etc.). One rule per bullet. Empty file = no universal rules.
- `payloads.py` — `build_global_chat_payload`, `build_workflow_chat_payload`,
  `build_job_chat_payload`. Intuitive named kwargs that translate to the JSON
  shape each service expects.
- `responses.py` — `get_attachment`, `assert_routed_to`, `assert_agent_calls`.
  Shared response helpers used across acceptance tests.
- `apollo_client.py` — `ApolloClient` for dispatching to a chat service.
  Currently a subprocess-based stub; the integration tier will replace its
  internals with a real HTTP client.
- `fixtures.py` — pytest fixtures (`apollo_client`). Registered via
  `pytest_plugins = ["testing.fixtures"]` in the repo-root `conftest.py`.

## Why under `services/` and not a top-level `tests/`?

Imports across the codebase resolve relative to `services/` (see
`CLAUDE.md` → "Python Import Patterns"). Putting helpers here means tests
import without path-munging hacks, the same way services do `from util
import …`.

The Bun service auto-discovery in `platform/src/util/describe-modules.ts`
skips this directory because it has no `testing.py` index file.
