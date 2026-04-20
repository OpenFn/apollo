---
paths:
  - "services/**/*.py"
---

# Python service conventions

## Entry point

All services are invoked via `services/entry.py`, which does
`__import__("<service>.<service>")` and calls `main(data)`. This means:

- Every service must export `def main(data_dict: dict) -> dict:`
- `data_dict` is the JSON request body parsed to a dict
- Return value is a dict serialized back to JSON
- `entry.py` handles dotenv, Sentry init, and argparse — services don't need to

## Imports

Because `entry.py` is the process entry point, the Python path root is
`services/`. This affects how imports work:

- **Same service**: relative imports (`from .prompt import build_prompt`)
- **Shared utils at services root**: absolute (`from util import create_logger`)
- **Cross-service**: absolute by service name (`from inference import inference`)

Do not add `sys.path` hacks — they are unnecessary given entry.py sets the path.

## Code quality

- Run Python tests with `poetry run pytest <path>` from the repo root.
  Tests live in `services/<service>/tests/`.
- If you changed streaming behavior, test the `/stream` endpoint: check if port
  3000 is already in use. If not, start `bun dev`, run the test, then stop it.
  If the server was already running, leave it running after testing.
  Test with `curl -N -X POST http://localhost:3000/services/<name>/stream`
  and verify SSE events are emitted.
- After editing Python files, run `ruff check` on the files you changed and fix
  issues. Don't run it on files you didn't touch.
- Don't reformat code you didn't change.
