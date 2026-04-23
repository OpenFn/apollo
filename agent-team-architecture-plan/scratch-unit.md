# scratch notes — unit tests architect

Key facts gathered:
- Python 3.11 only. Poetry in-project `.venv`. `pytest ^8.4.1` already declared.
- No `conftest.py`, no `pytest.ini`, no `[tool.pytest.ini_options]` block in pyproject today.
- No GitHub Actions CI for tests today. `.github/workflows/` only has `auto-tag.yaml` and `dockerize.yaml`.
- Each chat service uses `sys.path.insert(0, str(services_dir))` pattern inside its test files — this is a pytest path hack to reach sibling services. Should be replaced with pyproject `pythonpath` config.
- Existing unit-flavored files:
  - `services/job_chat/tests/test_functions.py` — mixed: some tests touch real Postgres and real LLM (NOT unit by our definition). Only a couple could become pure unit.
  - `services/workflow_chat/tests/test_functions.py` — genuinely unit-style: tests `AnthropicClient.extract_and_preserve_components`, `.sanitize_job_names`, `build_prompt`. Only real dep is `AnthropicClient(ChatConfig(api_key="fake-key"))` instantiation — that's fine, no network.
  - `services/global_chat/tests/` has no `test_functions.py` yet, but `yaml_utils.py`, `config_loader.py`, `router.py` (the `RouterDecision` parsing), and tools/tool_definitions are unit-testable.
- TS side: `bun:test` runs files in `platform/test/`. Out of scope for now (not in chat services).
- Langfuse added to pyproject — `@observe` decorator wraps `main()`. Unit tests must not trigger live langfuse. Needs env guard in conftest.
- `services/util.py` contains pure fns: `AdaptorSpecifier`, `DictObj`, `sum_usage`, `add_page_prefix`. All unit-testable.

Decisions:
- Runner: pytest only for Python. `bun:test` stays where it is for the platform layer.
- Folder per layer inside each service's tests/: `unit/`, `service/`, `integration/`, `acceptance/`.
- Shared helpers live in `services/_testing/` (underscore = skipped by describe-modules.ts auto-mount).
- Root `conftest.py` at `services/conftest.py` — handles env-guarding for unit runs (disable network, disable langfuse, sets dummy API keys).
- pyproject adds `[tool.pytest.ini_options]`: pythonpath=services, markers, testpaths.
- CI: new `.github/workflows/python-unit-tests.yaml`, runs `poetry run pytest -m unit` on every push to an open PR.
- Marker `@pytest.mark.unit` is default for everything under `*/tests/unit/`. Enforced by addopts + per-folder conftest that auto-applies the marker.

Mock-ish concerns avoided:
- Unit tests must not spawn the bridge subprocess, must not open Postgres, must not hit Pinecone, must not call Anthropic. No real `AnthropicClient` network config is required because the class can be instantiated without making a call (confirmed in existing workflow_chat/test_functions.py).
