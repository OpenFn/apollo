"""Reuse Langfuse/OTel spans to time a request, for latency profiling in tests.

Every chat service is already instrumented: `@observe` wraps the orchestration
steps (global_chat, router, planner, subagents) and `AnthropicInstrumentor`
wraps each model call. Those spans already carry start/end timestamps — this
module piggybacks on them rather than adding any new timing.

`install()` registers an SDK TracerProvider with a lightweight processor *before*
Langfuse is constructed. Langfuse then reuses that provider (see
`langfuse/_client/resource_manager.py`), so its export is unaffected; we just get
a second, local view of the same spans. The processor only appends to an
in-memory list per span — no I/O during the request — and dumps a readable table
to stderr once at process exit.

This is loaded only in the test subprocess (via the `_bootstrap/sitecustomize.py`
shim on a test-only PYTHONPATH, gated on `APOLLO_TIMING`), so production never
touches it.
"""

import atexit
import sys

from opentelemetry import trace as trace_api
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider


class _TimingProcessor(SpanProcessor):
    """Records (start_time, name, duration_ms) for every span that ends."""

    def __init__(self):
        self.records = []

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        try:
            duration_ms = (span.end_time - span.start_time) / 1e6
            self.records.append((span.start_time, span.name, duration_ms))
        except Exception:
            # Never let timing capture affect the request
            pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


_installed = False


def install():
    """Register a local timing provider before Langfuse builds its own.

    Idempotent. Safe to call from sitecustomize at interpreter startup.
    """
    global _installed
    if _installed:
        return
    _installed = True

    processor = _TimingProcessor()
    provider = TracerProvider()
    provider.add_span_processor(processor)
    trace_api.set_tracer_provider(provider)
    atexit.register(_flush, processor)


def _flush(processor):
    """Print a chronological span timing table to stderr at exit."""
    if not processor.records:
        return
    processor.records.sort(key=lambda r: r[0])
    lines = ["", "=== SPAN TIMINGS (ms) ==="]
    for _, name, duration_ms in processor.records:
        lines.append(f"{name:<36} {duration_ms:>10.1f}")
    lines.append("=========================")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()
