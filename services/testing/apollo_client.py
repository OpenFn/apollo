"""Client for dispatching to chat services in acceptance tests.

This is a **stub** — it shells out to `services/entry.py` via subprocess, the
same pattern the existing `tests/test_utils.py` files use. The integration
tier will replace the implementation with a real HTTP client backed by a
session-scoped `apollo_server` fixture (`bun run start`), keeping the same
`.call()` signature so acceptance tests don't need to change.

The stub is deliberately minimal:
- One method: `.call(service_name, payload)`.
- No streaming, no WebSocket support — acceptance dispatches synchronous JSON.
- No retry, no timeout config — failures surface as `RuntimeError` for the
  test to handle.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


_ENTRY_PY = Path(__file__).parent.parent / "entry.py"
_SERVICES_DIR = Path(__file__).parent.parent


class ApolloClient:
    """Dispatches a JSON payload to a chat service and returns the response dict.

    Today: spawns `python entry.py <service>` per call.
    Future (integration tier): POSTs to a long-lived bun server.
    """

    def call(self, service_name: str, payload: dict) -> dict[str, Any]:
        """Invoke `service_name` with `payload`. Returns the parsed JSON response.

        Raises RuntimeError if the service exits non-zero.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as input_file:
            json.dump(payload, input_file, indent=2)
            input_path = input_file.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as output_file:
            output_path = output_file.name

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(_ENTRY_PY),
                    service_name,
                    "--input", input_path,
                    "--output", output_path,
                ],
                capture_output=True,
                text=True,
                cwd=_SERVICES_DIR,
            )
            # Forward the subprocess's stdout/stderr to the test runner so
            # logger output from the service is visible under `pytest -s`.
            # Without this, Python logs sink into the captured buffers and
            # silently disappear on success.
            if result.stdout:
                sys.stdout.write(result.stdout)
            if result.stderr:
                sys.stderr.write(result.stderr)
            if result.returncode != 0:
                raise RuntimeError(
                    f"{service_name} exited {result.returncode}.\n"
                    f"stderr:\n{result.stderr}"
                )
            with open(output_path) as f:
                return json.load(f)
        finally:
            for path in (input_path, output_path):
                try:
                    Path(path).unlink()
                except OSError:
                    pass
