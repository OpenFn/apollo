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

A service that calls apollo() mid-run talks to the bridge over the same socket:
  child  -> bridge : CALL:<id>:{"service","payload"}   (blocks the child)
  bridge -> child  : REPLY:<id>:<json result>

so a self-call runs in the bridge process with no second HTTP hop.
"""

import argparse
import importlib
import itertools
import json
from collections.abc import Callable
from typing import TextIO
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


_call_ids = itertools.count(1)


def _make_fork_call(reader: TextIO) -> Callable[[str, dict], dict]:
    """Build the apollo() transport for one child: send a CALL line, block on
    its REPLY. One request/reply at a time, which matches apollo()'s blocking
    HTTP contract, so a plain line scan is enough - no id demultiplexing."""

    def fork_call(service: str, payload: dict) -> dict:
        call_id = next(_call_ids)
        # CALL rides stdout (fd 1 = the socket) exactly like a log or EXIT line
        print("CALL:" + str(call_id) + ":" + json.dumps({"service": service, "payload": payload}))
        prefix = "REPLY:" + str(call_id) + ":"
        for raw in reader:
            line = raw.rstrip("\n")
            if line.startswith(prefix):
                return json.loads(line[len(prefix):])
            # any other inbound line is unexpected on this half of the socket
        raise RuntimeError("apollo(" + service + "): socket closed before REPLY")

    return fork_call


def run_child(conn: socket.socket, req: dict) -> None:
    """In the forked child: stream through the socket, run one job, exit."""
    # Route stdout to the socket so the service's logging reaches the bridge.
    # Leave stderr on fd 2 (the master's stderr pipe) so Python tracebacks still
    # reach the server logs, the way the spawn path forwards them.
    os.dup2(conn.fileno(), 1)
    sys.stdout = os.fdopen(1, "w", buffering=1)

    # apollo() rides this same socket: a CALL line goes out on stdout and the
    # bridge writes a REPLY line back, which we read here. conn (the original
    # fd, still open alongside the dup) is the inbound half.
    import util

    reader = conn.makefile("r", encoding="utf-8")
    util.set_fork_call(_make_fork_call(reader))

    print(f"PID:{os.getpid()}")  # first, so the bridge can cancel this child

    code = 0
    try:
        import entry  # post-fork: entry.py's init runs here (fork-safe), deps warm

        sentry_sdk.set_tag("service", req["service"])  # entry.main() tags it; call() doesn't
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
