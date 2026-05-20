# services/testing

Shared helpers for the test suite.

This directory is on the Python path via `pyproject.toml`
(`pythonpath = ["services"]`), so tests import as
`from testing.yaml_assertions import assert_yaml_equal_except`.

## Modules

- `yaml_assertions.py` — pure-function YAML structural assertions, safe for
  every tier (unit included).
- `judge.py` — LLM-as-judge helper for acceptance tests. Evaluates chat-service
  responses against natural-language criteria under a named judge. Defaults to
  `CLAUDE_SONNET` from `services/models.py` and the `general` judge.
- `judges.py` — registry that loads judge configs from `judges/<name>.md`.
- `judges/` — one markdown file per named judge. Each has a `# role` section
  (who the judge is and what it evaluates) and a `# rules` section (universal
  bullets that apply to every evaluation under this judge). Today: `general`
  and `openfn_code_quality`. Specs select judges via the `judges:` frontmatter
  field; default is `[general]`.
- `spec_parser.py` — parses acceptance test markdown specs
  (`services/<svc>/tests/acceptance/*.md`) into `Spec` dataclasses.
- `spec_collector.py` — pytest plugin (registered via `pytest_plugins` in the
  repo-root `conftest.py`). Turns each MD spec into a pytest item that builds
  the service payload, calls the service via `ApolloClient`, and runs the judge.
  Any project YAML in the response (`response_yaml`, `workflow_yaml`,
  `content_yaml`, or a `workflow_yaml` attachment) is written to a `tmp/`
  folder next to the spec file (e.g.
  `services/workflow_chat/tests/acceptance/tmp/<spec_id>.yaml`) for inspection.
- `apollo_client.py` — `ApolloClient` for dispatching to a chat service.
  Currently a subprocess-based stub; the integration tier will replace its
  internals with a real HTTP client (same `.call()` signature, no test changes).

## Why under `services/` and not a top-level `tests/`?

Imports across the codebase resolve relative to `services/` (see
`CLAUDE.md` → "Python Import Patterns"). Putting helpers here means tests
import without path-munging hacks, the same way services do `from util
import …`.

The Bun service auto-discovery in `platform/src/util/describe-modules.ts`
skips this directory because it has no `testing.py` index file.
