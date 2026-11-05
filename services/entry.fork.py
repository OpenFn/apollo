"""Fork entry for the Python side (used when APOLLO_FORK_SERVER=true; see
platform/src/bridge.fork.ts). Run as a script, never imported.

Pays the heavy imports once, then forks a fresh child per request. Each child
inherits the imports via copy-on-write and imports entry.py AFTER forking, so
entry.py's own init runs in the child where it's fork-safe - entry.py is left
untouched. The parent only imports and never inits, so it stays forkable.

macOS: set OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES in your env (see .env.example),
or a forked child that touches an Objective-C framework aborts. No-op on Linux.

Protocol (NDJSON over a unix socket, one connection per request):
  bridge -> master : {"service","payload","port"}
  child  -> bridge : PID:<pid>  then the service's stdout  then RESULT:<json>
                     then EXIT:<code>

The payload rides in on the request and the result rides back as a RESULT line,
so this path touches no tmp/data files at all (the spawn path still does).
"""

import argparse
import importlib
import json
import os
import signal
import socket
import sys
import traceback
from pathlib import Path

import sentry_sdk  # for the per-child service tag + flush (see run_child)
import yaml

# Warm entry.py's heavy deps so forked children inherit them (copy-on-write).
# See fork_preload.yaml for the list and why each module is there.
PRELOAD_PATH = Path(__file__).parent / "fork_preload.yaml"


def preload() -> int:
    """Warm the shared deps, plus any opt-in services. Services are opt-in
    (APOLLO_FORK_PRELOAD_SERVICES) because some do I/O at import and would hang
    the parent; the child imports the rest on demand."""
    with PRELOAD_PATH.open() as f:
        modules = yaml.safe_load(f)["preload"]
    for module in modules:
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
    # Route stdout to the socket so the service's logging reaches the bridge.
    # Leave stderr on fd 2 (the master's stderr pipe) so Python tracebacks still
    # reach the server logs, the way the spawn path forwards them.
    os.dup2(conn.fileno(), 1)
    sys.stdout = os.fdopen(1, "w", buffering=1)

    print(f"PID:{os.getpid()}")  # first, so the bridge can cancel this child

    code = 0
    try:
        import entry  # post-fork: entry.py's init runs here (fork-safe), deps warm

        sentry_sdk.set_tag("service", req["service"])  # entry.main() tags it; call() doesn't
        result = entry.call(
            service=req["service"],
            data=req.get("payload") or {},
            apollo_port=req.get("port"),
        )
        # json.dumps escapes newlines inside strings, so this is always one line
        print("RESULT:" + json.dumps(result))
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        try:
            sentry_sdk.flush(timeout=2)
        except Exception:
            pass
        langfuse = getattr(sys.modules.get("entry"), "langfuse", None)
        if langfuse is not None:
            try:
                langfuse.flush()
            except Exception:
                pass
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
        # Fork before reading: the request now carries the whole payload, so
        # reading it here would let one slow or stalled client hold up every
        # other request. The child reads its own, and the master only accepts
        # and forks.
        if os.fork() == 0:
            server.close()  # the child must not hold the listening socket
            try:
                req = read_request(conn)
            except OSError:  # peer reset mid-read; same as no usable request
                req = None
            if req is None:
                conn.close()
                os._exit(0)
            run_child(conn, req)  # never returns
        conn.close()  # parent drops its copy; the child owns the reply


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    serve(parser.parse_args().socket)
