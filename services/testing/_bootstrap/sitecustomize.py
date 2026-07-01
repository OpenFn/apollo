"""Auto-loaded at interpreter startup *only* when this dir is on PYTHONPATH.

The test harness (services/testing/apollo_client.py) prepends this directory to
the child process's PYTHONPATH when APOLLO_TIMING is set, so Python imports this
module during site initialisation — before entry.py runs. We use that early hook
to install span timing before Langfuse constructs its tracer provider.

Double-gated: this dir is only on PYTHONPATH during timed test runs, and we also
check APOLLO_TIMING here, so it can never fire in production.
"""

import os
import sys
from pathlib import Path

if os.environ.get("APOLLO_TIMING"):
    # services/testing/_bootstrap/sitecustomize.py -> parents[2] = services/
    services_dir = str(Path(__file__).resolve().parents[2])
    if services_dir not in sys.path:
        sys.path.insert(0, services_dir)

    from testing.span_timing import install

    install()
