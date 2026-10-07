"""Fork entry for the Python side (used when APOLLO_FORK_SERVER=true; see
platform/src/bridge.fork.ts). Run as a script, never imported.

Pays the heavy imports once, then forks a fresh child per request. Each child
inherits the imports via copy-on-write and imports entry.py AFTER forking, so
entry.py's own init runs in the child where it's fork-safe - entry.py is left
untouched. The parent only imports and never inits, so it stays forkable.

macOS: set OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES in your env (see .env.example),
or a forked child that touches an Objective-C framework aborts. No-op on Linux.

Protocol (NDJSON over a unix socket, one connection per request):
  bridge -> master : {"service","input","output","port"}
  child  -> bridge : PID:<pid>  then the service's stdout  then EXIT:<code>
"""

import argparse
import importlib
import json
import os
import signal
import socket
import sys
import traceback

# Warm entry.py's heavy deps so forked children inherit them (copy-on-write).
# Mirrors entry.py's imports; a missing one is just imported per-child - slower,
# never wrong.
PRELOAD = (
    "sentry_sdk",
    "anthropic",
    "langfuse",
    "langfuse_util",
    "util",
    "opentelemetry.instrumentation.anthropic",
    "opentelemetry.instrumentation.threading",
)


def preload() -> int:
    """Warm the shared deps, plus any opt-in services. Services are opt-in
    (APOLLO_FORK_PRELOAD_SERVICES) because some do I/O at import and would hang
    the parent; the child imports the rest on demand."""
    for module in PRELOAD:
        importlib.import_module(module)

    names = [s.strip() for s in os.environ.get("APOLLO_FORK_PRELOAD_SERVICES", "").split(",") if s.strip()]
    loaded = 0
    for name in names:
        try:
            importlib.import_module(f"{name}.{name}")
            loaded += 1
        except Exception as e:
            print(f"entry.fork: could not preload {name}: {e}", file=sys.stderr, flush=True)
    return loaded


def run_child(conn: socket.socket, req: dict) -> None:
    """In the forked child: stream through the socket, run one job, exit."""
    # Route stdout/stderr to the socket so the service's logging reaches the bridge.
    os.dup2(conn.fileno(), 1)
    os.dup2(conn.fileno(), 2)
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)

    print(f"PID:{os.getpid()}")  # first, so the bridge can cancel this child

    code = 0
    try:
        import entry  # post-fork: entry.py's init runs here (fork-safe), deps warm

        entry.call(
            service=req["service"],
            input_path=req.get("input"),
            output_path=req.get("output"),
            apollo_port=req.get("port"),
        )
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        print(f"EXIT:{code}")
    os._exit(code)


def read_request(conn: socket.socket) -> dict | None:
    """Read one newline-terminated JSON request; None if there isn't a usable one."""
    line = b""
    while not line.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        line += chunk
    try:
        return json.loads(line) if line else None
    except json.JSONDecodeError:
        return None


def serve(sock_path: str) -> None:
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # auto-reap children
    count = preload()

    if os.path.exists(sock_path):
        os.unlink(sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(128)
    print(f"READY services={count}", flush=True)  # handshake the bridge waits for

    while True:
        try:
            conn, _ = server.accept()
        except InterruptedError:
            continue
        req = read_request(conn)
        if req is None:
            conn.close()
            continue
        if os.fork() == 0:
            server.close()  # the child must not hold the listening socket
            run_child(conn, req)  # never returns
        conn.close()  # parent drops its copy; the child owns the reply


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    serve(parser.parse_args().socket)
