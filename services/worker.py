"""
Long-lived Python worker for the Apollo Bun server.

Connects to the Bun-owned Unix domain socket (APOLLO_SOCKET_PATH), receives
newline-delimited-JSON START messages, and runs each job on its own thread.
LOG/EVENT/STATUS/END/ERROR messages are streamed back over the same socket via
a single writer thread (so NDJSON framing can never interleave). Replaces the
per-request `poetry run python entry.py` spawn; `entry.py` remains the standalone
`bun py` entrypoint.
"""

import contextlib
import contextvars
import ctypes
import json
import os
import queue
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

import sentry_sdk
from dotenv import load_dotenv
from langfuse import Langfuse
from langfuse.span_filter import is_default_export_span
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor
from util import ApolloError, set_apollo_port, set_job_writer

# Langfuse/OTel init: once per process, before any Anthropic client is created.
# Moved here from entry.py (the worker is now the long-lived process; entry.py
# keeps its own copy for the standalone path). load_dotenv first so the Langfuse
# client and Sentry read the environment.
load_dotenv()
AnthropicInstrumentor().instrument()
ThreadingInstrumentor().instrument()


def _should_export_span(span: Any) -> bool:  # noqa: ANN401
    """Drop spans marked as tracing-disabled (user has not opted in)."""
    attrs = getattr(span, "attributes", None) or {}
    if attrs.get("langfuse.trace.metadata.tracing_disabled") == "true":
        return False
    return is_default_export_span(span)


langfuse = Langfuse(should_export_span=_should_export_span, release=os.getenv("APOLLO_VERSION", "unknown"))

_env = os.getenv("ENVIRONMENT", "unknown")
_trace_rates = {
    "development": 1,
    "staging": 0.05,
    "production": 0.03,
    "unknown": 0.0,
}

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=_env,
    sample_rate=1.0,
    traces_sample_rate=_trace_rates.get(_env, 0.0),
    enable_tracing=True,
    auto_enabling_integrations=False,
)

# Terminal/control messages must never be dropped; noisy per-job LOG/STATUS may be
# under backpressure. The ready handshake is a STATUS with job_id null and is
# treated as non-droppable.
_DROPPABLE = {"LOG", "STATUS"}
_QUEUE_MAXSIZE = 10000

_sock: socket.socket | None = None
_send_queue: "queue.Queue[dict | None]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)


def _enqueue(msg: dict) -> None:
    """Queue a framed message for the writer thread, applying the drop policy."""
    if msg.get("type") in _DROPPABLE and msg.get("job_id") is not None:
        with contextlib.suppress(queue.Full):  # droppable under pressure
            _send_queue.put_nowait(msg)
    else:
        _send_queue.put(msg)


def _writer_loop() -> None:
    """Single owner of the socket write end: one whole line per send."""
    while True:
        msg = _send_queue.get()
        if msg is None:
            return
        line = (json.dumps(msg) + "\n").encode("utf-8")
        try:
            _sock.sendall(line)
        except OSError:
            # Socket gone (parent died). Nothing more to do; read loop exits too.
            return


def _make_writer(job_id: str) -> Callable[[dict], None]:
    """Writer closure bound to one job — attaches job_id so callers need not."""
    def writer(msg: dict) -> None:
        _enqueue({**msg, "job_id": job_id})
    return writer


def _run_job(job_id: str, service: str, payload: dict, port: int | None) -> None:
    """Run one service under the current (per-job) context. Guarantees exactly
    one terminal END/ERROR message."""
    set_job_writer(_make_writer(job_id))
    if port is not None:
        set_apollo_port(port)

    sentry_sdk.set_tag("service", service)
    try:
        m = __import__(f"{service}.{service}", fromlist=["main"])
        result = m.main(payload)
        _enqueue({"type": "END", "job_id": job_id, "result": result})
    except ApolloError as e:
        sentry_sdk.capture_exception(e)
        d = e.to_dict()
        err = {
            "type": "ERROR",
            "job_id": job_id,
            "code": d["code"],
            "message": d["message"],
            "error_type": d.get("type", "APOLLO_ERROR"),
        }
        if d.get("details"):
            err["details"] = d["details"]
        _enqueue(err)
    except Exception as e:  # ModuleNotFoundError etc. -> 500
        sentry_sdk.capture_exception(e)
        _enqueue({
            "type": "ERROR",
            "job_id": job_id,
            "code": 500,
            "message": str(e),
            "error_type": "INTERNAL_ERROR",
        })
    finally:
        with contextlib.suppress(Exception):
            langfuse.flush()


def _dispatch_job(job_id: str, service: str, payload: dict, port: int | None) -> None:
    """Run the job in a fresh context so its writer (and any copy_context pools it
    spawns) are isolated per job."""
    ctx = contextvars.copy_context()
    ctx.run(_run_job, job_id, service, payload, port)


def _handle_message(msg: dict) -> None:
    if msg.get("type") != "START":
        return
    job_id = msg.get("job_id")
    service = msg.get("service")
    payload = msg.get("payload") or {}
    port = msg.get("port")
    threading.Thread(
        target=_dispatch_job,
        args=(job_id, service, payload, port),
        daemon=True,
    ).start()


def _read_loop() -> None:
    """Read NDJSON from the socket, dispatch each START on its own thread. Exits
    (and ends the process) when the socket closes — i.e. Bun went away."""
    buf = b""
    while True:
        try:
            chunk = _sock.recv(65536)
        except OSError:
            break
        if not chunk:
            break  # Bun closed the connection
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:  # skip a malformed/spliced line
                continue
            _handle_message(msg)


def _connect_with_retry(path: str, timeout: float = 30.0) -> socket.socket:
    """Bun creates+binds the socket; give it a short grace to appear on startup."""
    deadline = time.time() + timeout
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
            return s
        except OSError:
            s.close()
            if time.time() > deadline:
                raise
            time.sleep(0.1)


def _install_parent_death_signal() -> None:
    """On Linux, ask the kernel to signal us when our parent dies (Bun crash with
    no clean SIGTERM). Best-effort; the ppid watcher backstops it."""
    if sys.platform != "linux":
        return
    with contextlib.suppress(Exception):
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1  # noqa: N806
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def _watch_parent() -> None:
    """Portable backstop: exit if we get reparented (parent died)."""
    initial = os.getppid()
    while True:
        time.sleep(2)
        if os.getppid() != initial:
            os._exit(0)


def main() -> None:
    _install_parent_death_signal()

    socket_path = os.environ.get("APOLLO_SOCKET_PATH")
    if not socket_path:
        print("APOLLO_SOCKET_PATH not set; worker cannot start", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    global _sock  # noqa: PLW0603
    _sock = _connect_with_retry(socket_path)

    threading.Thread(target=_writer_loop, daemon=True).start()
    threading.Thread(target=_watch_parent, daemon=True).start()

    # Ready handshake: carries the shared internal token so Bun can authenticate
    # "this is the child I spawned" (constant-time compare) before going live.
    _send_queue.put({
        "type": "STATUS",
        "job_id": None,
        "data": {"ready": True},
        "token": os.environ.get("APOLLO_INTERNAL_TOKEN", ""),
    })

    _read_loop()
    # Socket closed -> parent gone. Exit hard so we don't hold keys or bill LLM calls.
    os._exit(0)


if __name__ == "__main__":
    main()
