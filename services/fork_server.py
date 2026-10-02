import os
import sys

# macOS aborts a forked child that touches an objc framework unless this is set
# before interpreter start, so re-exec once with it in the env. No-op on Linux.
# [To be removed]
if sys.platform == "darwin" and os.environ.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY") != "YES":
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], os.environ)

# Tell entry.py to import its heavy modules but defer bootstrap() to each child.
os.environ["APOLLO_FORK_PRELOAD"] = "1"

import argparse  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import signal  # noqa: E402
import socket  # noqa: E402
import traceback  # noqa: E402

import entry  # noqa: E402


def _preload_services() -> list[str]:
    """Import an opt-in allowlist (APOLLO_FORK_PRELOAD_SERVICES) so children
    inherit their deps. Not every service: some do I/O at import and would hang
    the parent; entry.call() imports the rest on demand in the child."""
    names = [n.strip() for n in os.environ.get("APOLLO_FORK_PRELOAD_SERVICES", "").split(",") if n.strip()]
    loaded = []
    for name in names:
        try:
            importlib.import_module(f"{name}.{name}")
            loaded.append(name)
        except Exception as e:
            print(f"fork_server: could not preload {name}: {e}", file=sys.stderr, flush=True)
    return loaded


def _run_child(conn: socket.socket, req: dict) -> None:
    os.dup2(conn.fileno(), 1)
    os.dup2(conn.fileno(), 2)
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)

    sys.stdout.write(f"PID:{os.getpid()}\n")  # first, so the bridge can cancel this child
    sys.stdout.flush()

    code = 0
    try:
        entry.bootstrap()
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
        sys.stdout.write(f"EXIT:{code}\n")
        sys.stdout.flush()
    os._exit(code)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", required=True)
    args = ap.parse_args()

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # auto-reap children

    loaded = _preload_services()

    if os.path.exists(args.socket):
        os.unlink(args.socket)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(args.socket)
    srv.listen(128)
    print(f"READY services={len(loaded)}", flush=True)  # handshake the bridge waits for

    while True:
        try:
            conn, _ = srv.accept()
        except InterruptedError:
            continue
        line = b""
        while not line.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            line += chunk
        if not line:
            conn.close()
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            conn.close()
            continue

        if os.fork() == 0:
            srv.close()  # the child must not hold the listening socket
            _run_child(conn, req)  # never returns
        conn.close()  # parent drops its copy; the child owns the reply


if __name__ == "__main__":
    main()
