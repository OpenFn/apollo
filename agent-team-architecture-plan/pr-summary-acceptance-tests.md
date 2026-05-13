# Acceptance tests architecture (draft PR summary)

Acceptance tests live next to the service they test, in `services/<svc>/tests/acceptance/`. Each test is a normal Python file. It builds a payload with an intuitive helper, calls the service, runs structural assertions, then calls an LLM judge for natural-language quality checks. The judge takes a `QUALITY_CRITERIA` list (one bullet per criterion, easy for non-technical contributors to edit) and also flags anything else notable. Universal rules in `services/testing/judge_rules.md` apply to every evaluation. The repo-root `conftest.py` auto-applies the `acceptance` marker by folder name, so `pytest -m acceptance` selects every test with no manual decoration. Acceptance is run on demand only, not in any automated pipeline. The 17 existing qualitative tests have been migrated; their originals are deleted.

## Tree

```
services/
  testing/
    judge.py              # LLM judge: criteria + general_flags + Verdict
    judge_rules.md        # universal rules, applied to every evaluation
    payloads.py           # build_{global,workflow,job}_chat_payload
    responses.py          # get_attachment, assert_routed_to, assert_agent_calls
    apollo_client.py      # ApolloClient (subprocess stub; integration tier will swap to HTTP)
    fixtures.py           # session-scoped apollo_client fixture
    yaml_assertions.py    # already shipped in #486
  global_chat/tests/acceptance/    # 5 tests
  workflow_chat/tests/acceptance/  # 9 tests
  job_chat/tests/acceptance/       # 6 tests
conftest.py               # registers pytest_plugins = ["testing.fixtures"]
agent-team-architecture-plan/
  4-acceptance-tests.md   # full architecture doc
```

## Key ideas

- One Python file per test. Each has a `QUALITY_CRITERIA = [...]` constant at the top.
- Three judge layers: universal rules, per-test criteria, open-ended "flag anything else notable".
- Payload builders use user-facing kwargs (`current_job_code`, `current_adaptor`, `previous_page`) and translate to the underlying JSON shape.
- Structural assertions stay deterministic Python. The LLM judge is one assertion among several, not the whole test.
- Multi-run sampling is plain `@pytest.mark.parametrize("_run", range(N))`. Nothing custom.
- The integration tier will replace the `ApolloClient` internals with a real HTTP client. No test changes required.
