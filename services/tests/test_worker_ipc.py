"""Unit tests for the Python side of the Bun<->Python Unix-socket worker.

Covers the shared logging/streaming plumbing (util.create_logger, the job-writer
ContextVar, StreamManager._emit_event) and worker.py's single-writer framing +
per-job terminal handling. All deterministic; no LLM/network calls.

Run from repo root:
    poetry run pytest services/tests/test_worker_ipc.py
"""
import contextvars
import json
import queue
import socket
import sys
import threading
import types
from collections.abc import Callable

import pytest
import streaming_util
import util
import worker
from util import ApolloError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_job_writer():
    """No writer leaks between tests (the writer is a process-wide ContextVar in
    the test's own context)."""
    util.set_job_writer(None)
    yield
    util.set_job_writer(None)


# --------------------------------------------------------------------------- #
# util.create_logger — single emission path (socket XOR stdout, never both)
# --------------------------------------------------------------------------- #

class TestCreateLogger:
    def test_writer_present_enqueues_log_and_skips_stdout(self, capsys):
        captured: list[dict] = []
        util.set_job_writer(captured.append)

        log = util.create_logger("job_chat")
        log.info("hello from a job")

        assert len(captured) == 1
        msg = captured[0]
        assert msg["type"] == "LOG"
        assert msg["level"] == "INFO"
        assert msg["source"] == "job_chat"
        assert msg["message"] == "hello from a job"
        # Must NOT also hit stdout (no double-emit).
        assert "hello from a job" not in capsys.readouterr().out

    def test_no_writer_writes_stdout_exactly_once(self, capsys):
        util.set_job_writer(None)

        log = util.create_logger("standalone_svc")
        log.info("unique-stdout-token-xyz")

        out = capsys.readouterr().out
        assert out.count("unique-stdout-token-xyz") == 1

    def test_emit_never_raises_when_writer_absent(self):
        util.set_job_writer(None)
        log = util.create_logger("noraise")
        # Should not raise regardless of content.
        log.info("plain")
        log.warning("with %s formatting", "arg")


# --------------------------------------------------------------------------- #
# set_job_writer / get_job_writer — contextvar isolation
# --------------------------------------------------------------------------- #

class TestJobWriterIsolation:
    def test_writer_set_in_copied_context_does_not_leak_out(self):
        util.set_job_writer(None)
        seen: dict = {}

        def inner_a():
            util.set_job_writer(lambda _m: None)
            seen["a"] = util.get_job_writer()

        def inner_b():
            seen["b"] = util.get_job_writer()

        contextvars.copy_context().run(inner_a)
        seen["outer_after_a"] = util.get_job_writer()
        contextvars.copy_context().run(inner_b)

        assert seen["a"] is not None          # writer visible inside its context
        assert seen["outer_after_a"] is None   # did not leak back to the parent
        assert seen["b"] is None               # nor into a sibling context

    def test_two_contexts_carry_independent_writers(self):
        util.set_job_writer(None)
        got: dict = {}

        def make(tag):
            # A distinct writer object per context so identity proves isolation.
            writer = {"tag": tag}
            def run():
                util.set_job_writer(writer.__setitem__)
                got[tag] = util.get_job_writer()
            return run

        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()
        ctx1.run(make("one"))
        ctx2.run(make("two"))

        assert got["one"] is not got["two"]
        assert util.get_job_writer() is None


# --------------------------------------------------------------------------- #
# streaming_util.StreamManager._emit_event
# --------------------------------------------------------------------------- #

class TestEmitEvent:
    def test_writer_present_sends_event_shape_with_job_id_from_closure(self, monkeypatch):
        # The writer closure (worker._make_writer) is what attaches job_id;
        # _emit_event itself only supplies type/event/data. Wire the real closure
        # to a captured _enqueue to lock in that contract.
        captured: list[dict] = []
        monkeypatch.setattr(worker, "_enqueue", captured.append)
        util.set_job_writer(worker._make_writer("job-123"))

        sm = streaming_util.StreamManager(stream=True)
        sm._emit_event("content_block_delta", {"index": 2})

        assert captured == [
            {
                "type": "EVENT",
                "event": "content_block_delta",
                "data": {"index": 2},
                "job_id": "job-123",
            },
        ]

    def test_no_writer_falls_back_to_event_stdout_protocol(self, capsys):
        util.set_job_writer(None)
        sm = streaming_util.StreamManager(stream=True)
        sm._emit_event("message_stop", {"type": "message_stop"})

        out = capsys.readouterr().out
        assert 'EVENT:message_stop:{"type": "message_stop"}' in out

    def test_no_writer_never_raises(self):
        util.set_job_writer(None)
        sm = streaming_util.StreamManager(stream=True)
        sm._emit_event("evt", {"a": 1})  # must not raise

    def test_non_streaming_manager_emits_nothing(self, capsys, monkeypatch):
        captured: list[dict] = []
        monkeypatch.setattr(worker, "_enqueue", captured.append)
        util.set_job_writer(worker._make_writer("j"))

        sm = streaming_util.StreamManager(stream=False)
        sm._emit_event("evt", {"a": 1})

        assert captured == []
        assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# worker._writer_loop — single writer serializes concurrent producers
# --------------------------------------------------------------------------- #

class TestWriterThreadFraming:
    def test_concurrent_enqueue_yields_whole_json_lines(self, monkeypatch):
        # Drive the real _enqueue/_writer_loop over a socketpair from many threads
        # and assert every received line is a complete, standalone JSON object —
        # i.e. no interleaving across the single writer.
        a, b = socket.socketpair()
        fresh_q: queue.Queue = queue.Queue(maxsize=100_000)
        monkeypatch.setattr(worker, "_sock", a)
        monkeypatch.setattr(worker, "_send_queue", fresh_q)

        received = bytearray()

        def reader():
            while True:
                chunk = b.recv(65536)
                if not chunk:
                    break
                received.extend(chunk)

        rt = threading.Thread(target=reader)
        rt.start()
        wt = threading.Thread(target=worker._writer_loop)
        wt.start()

        n_threads, per_thread = 8, 250

        def producer(tid: int):
            for i in range(per_thread):
                # EVENT is non-droppable, so nothing is lost under the drop policy.
                worker._enqueue({
                    "type": "EVENT",
                    "job_id": f"job-{tid}",
                    "event": "e",
                    "data": {"tid": tid, "i": i, "pad": "x" * 64},
                })

        producers = [threading.Thread(target=producer, args=(t,)) for t in range(n_threads)]
        for p in producers:
            p.start()
        for p in producers:
            p.join()

        fresh_q.put(None)   # stop the writer loop
        wt.join()
        a.close()           # EOF for the reader
        rt.join()
        b.close()

        text = received.decode("utf-8")
        assert text.endswith("\n")
        lines = [ln for ln in text.split("\n") if ln]
        assert len(lines) == n_threads * per_thread
        # Every line parses on its own -> no framing interleave.
        for ln in lines:
            obj = json.loads(ln)
            assert obj["type"] == "EVENT"


# --------------------------------------------------------------------------- #
# worker._run_job — exactly one terminal message per job
# --------------------------------------------------------------------------- #

def _install_fake_service(name: str, main_fn: Callable[[dict], dict]) -> None:
    """Register a fake `<name>.<name>` module so worker's
    __import__(f"{name}.{name}", fromlist=["main"]) resolves to it."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []  # mark as a package
    sub = types.ModuleType(f"{name}.{name}")
    sub.main = main_fn
    setattr(pkg, name, sub)
    sys.modules[name] = pkg
    sys.modules[f"{name}.{name}"] = sub


def _run_job_collecting(monkeypatch, service: str, payload: dict) -> list[dict]:
    """Run _run_job in a fresh context (as production does) with _enqueue and
    langfuse stubbed; return every enqueued message."""
    captured: list[dict] = []
    monkeypatch.setattr(worker, "_enqueue", captured.append)
    monkeypatch.setattr(worker, "langfuse", types.SimpleNamespace(flush=lambda: None))
    contextvars.copy_context().run(worker._run_job, "job-1", service, payload, None)
    return captured


class TestRunJobTerminal:
    def test_success_sends_exactly_one_end(self, monkeypatch):
        _install_fake_service("svc_ok", lambda payload: {"result": payload["x"] + 1})
        msgs = _run_job_collecting(monkeypatch, "svc_ok", {"x": 41})

        terminals = [m for m in msgs if m["type"] in ("END", "ERROR")]
        assert len(terminals) == 1
        end = terminals[0]
        assert end["type"] == "END"
        assert end["job_id"] == "job-1"
        assert end["result"] == {"result": 42}

    def test_apollo_error_sends_one_error_from_to_dict_with_details(self, monkeypatch):
        def boom(_payload):
            raise ApolloError(
                429, "slow down", type="RATE_LIMIT", details={"retry_after": 60},
            )

        _install_fake_service("svc_apollo", boom)
        msgs = _run_job_collecting(monkeypatch, "svc_apollo", {})

        terminals = [m for m in msgs if m["type"] in ("END", "ERROR")]
        assert len(terminals) == 1
        err = terminals[0]
        assert err["type"] == "ERROR"
        assert err["code"] == 429
        assert err["error_type"] == "RATE_LIMIT"
        assert err["message"] == "slow down"
        assert err["details"] == {"retry_after": 60}

    def test_generic_exception_sends_one_500_internal_error(self, monkeypatch):
        def boom(_payload):
            raise ValueError("kaboom")

        _install_fake_service("svc_boom", boom)
        msgs = _run_job_collecting(monkeypatch, "svc_boom", {})

        terminals = [m for m in msgs if m["type"] in ("END", "ERROR")]
        assert len(terminals) == 1
        err = terminals[0]
        assert err["type"] == "ERROR"
        assert err["code"] == 500
        assert err["error_type"] == "INTERNAL_ERROR"
        assert err["message"] == "kaboom"

    def test_missing_service_module_sends_one_500(self, monkeypatch):
        # ModuleNotFoundError from __import__ must map to a single 500 ERROR.
        msgs = _run_job_collecting(monkeypatch, "no_such_service_xyz", {})
        terminals = [m for m in msgs if m["type"] in ("END", "ERROR")]
        assert len(terminals) == 1
        assert terminals[0]["type"] == "ERROR"
        assert terminals[0]["code"] == 500
        assert terminals[0]["error_type"] == "INTERNAL_ERROR"


class TestEnqueueDropPolicy:
    def test_per_job_log_is_dropped_when_queue_full(self, monkeypatch):
        full_q: queue.Queue = queue.Queue(maxsize=1)
        full_q.put({"type": "seed"})  # occupy the only slot
        monkeypatch.setattr(worker, "_send_queue", full_q)

        # A per-job LOG is droppable, so it is dropped rather than blocking.
        worker._enqueue({"type": "LOG", "job_id": "j", "message": "noise"})

        assert full_q.get_nowait() == {"type": "seed"}  # LOG never landed
        assert full_q.empty()

    def test_end_is_non_droppable_and_blocks_until_space(self, monkeypatch):
        full_q: queue.Queue = queue.Queue(maxsize=1)
        full_q.put({"type": "seed"})
        monkeypatch.setattr(worker, "_send_queue", full_q)

        # END must not be dropped: the enqueue blocks until a slot frees up.
        def free_slot() -> None:
            threading.Event().wait(0.05)
            full_q.get()

        drainer = threading.Thread(target=free_slot)
        drainer.start()
        worker._enqueue({"type": "END", "job_id": "j", "result": {}})  # blocks, then lands
        drainer.join()

        assert full_q.get_nowait() == {"type": "END", "job_id": "j", "result": {}}
