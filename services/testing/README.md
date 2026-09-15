# services/testing

Shared helpers for the test suite.

This directory is on the Python path via `pyproject.toml`
(`pythonpath = ["services"]`), so tests import as
`from testing.yaml_assertions import assert_yaml_equal_except`.

## Test tiers

**The directory is the marker.** A test in `tests/<tier>/` is marked `<tier>`
automatically by the repo-root `conftest.py` — there is nothing to declare.
Pick the tier by what the test touches:

| Tier | Directory | Touches | Runs |
|---|---|---|---|
| `unit` | `tests/unit/` | Nothing. Network, subprocess, DB and LLM-client construction all raise `UnitTestViolation` | Every PR push |
| `service` | `tests/service/` | Real service handlers, with the LLM/HTTP clients mocked | On merge |
| `integration` | `tests/integration/` | Real LLM, Pinecone, Postgres | Manual / nightly |
| `acceptance` | `tests/acceptance/` | Real everything, judged by an LLM (the `.md` specs below) | Manual / nightly |

Two rules of thumb:

- **Assert on bytes, not on wording, wherever you can.** If the question is
  "did this content reach the model", that is a `service`-tier test with a
  scripted client — put an improbable canary in the input and assert it appears
  in the request. It is free, deterministic, and needs no human to read it.
  Reserve `acceptance` for the questions only a judge can answer: is the answer
  *good*.
- **A guard you have not seen fail is not a guard.** Break the code, watch the
  test go red, put it back.

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
  For inspection, three artifacts are written to a `tmp/` folder next to the
  spec file:
  - `<spec_id>.yaml` — any project YAML in the response (`response_yaml`,
    `workflow_yaml`, `content_yaml`, or a `workflow_yaml` attachment).
  - `<spec_id>.txt` — the response text, prefixed with the agent path
    (e.g. `agents: router -> planner -> job_code_agent`).
  - `<spec_id>.judges.txt` — the judge verdict(s) in the same format printed
    during the run (per-judge PASS/FAIL header + criteria/flags summary).

  Filenames use `__` as the metadata separator (the spec id and extension only
  use `.`/`-`), so they stay splittable. Multi-run specs append `__run-N`. Pass
  `-E <label>` / `--experiment=<label>` to append `__<label>` to every captured
  filename so runs with different settings or dates don't overwrite each other
  (e.g. `tmp/<spec_id>__sonnet-2026-06-29.txt`).
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
