"""Reuse Langfuse/OTel spans to time a request, for latency profiling in tests.

Every chat service is already instrumented: `@observe` wraps the orchestration
steps (global_chat, router, planner, subagents) and `AnthropicInstrumentor`
wraps each model call. Those spans already carry start/end timestamps and
parent links — this module piggybacks on them rather than adding any new
timing.

`install()` registers an SDK TracerProvider with a lightweight processor *before*
Langfuse is constructed. Langfuse then reuses that provider (see
`langfuse/_client/resource_manager.py`), so its export is unaffected; we just get
a second, local view of the same spans. The processor only appends to an
in-memory list per span — no I/O during the request — and dumps a readable
waterfall to stderr once at process exit (and to `<output>_timing.txt` next to
the run's `--output` file, when one was given).

The waterfall shows the span tree (indentation = ran inside), a bar per span
positioned on the request's wall-clock (overlapping bars = ran concurrently),
and a `self` column: the span's time *not* covered by its child spans. A
coverage check at the end flags non-leaf spans with significant unmeasured
self time, so slow un-instrumented steps can't hide between spans.

`install()` also patches the instrumentor's `AnthropicStream.__next__` to mark
the arrival of each stream's first `content_block_delta` (the first generated
token, thinking or text) as a span event on the `anthropic.chat` span. The
waterfall's `1st tok` column shows, per `anthropic.chat` call, the time from
the API call to that first token; non-streaming calls show `-`.

This is loaded only in the test subprocess (via the `_bootstrap/sitecustomize.py`
shim on a test-only PYTHONPATH, gated on `APOLLO_TIMING`), so production never
touches it.
"""

import atexit
import contextlib
import os
import sys
from pathlib import Path

from opentelemetry import trace as trace_api
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider

_BAR_WIDTH = 40
_PRECISE_BELOW_S = 10  # durations under this get two decimals instead of one
_GAP_THRESHOLD_NS = int(1e9)  # flag non-leaf spans with more unmeasured time than this

# _Record fields: start_ns, end_ns, name, span_id, parent_span_id (None for root)
_Record = tuple[int, int, str, int, "int | None"]

_FIRST_TOKEN_EVENT = "apollo.first_token"


class _TimingProcessor(SpanProcessor):
    """Records (start, end, name, span_id, parent_id) for every span that ends."""

    def __init__(self) -> None:
        self.records: list[_Record] = []
        self.first_token_marks: list[tuple[int, int]] = []  # (owner_span_id, timestamp_ns)

    def on_start(self, span: Span, parent_context: "Context | None" = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        try:
            parent_id = span.parent.span_id if span.parent else None
            self.records.append(
                (span.start_time, span.end_time, span.name, span.context.span_id, parent_id),
            )
            for event in span.events or ():
                if event.name == _FIRST_TOKEN_EVENT:
                    self.first_token_marks.append((span.context.span_id, event.timestamp))
        except Exception:
            # Never let timing capture affect the request
            pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002 (OTel interface)
        return True


_installed = False


def install() -> None:
    """Register a local timing provider before Langfuse builds its own.

    Idempotent. Safe to call from sitecustomize at interpreter startup.
    """
    global _installed  # noqa: PLW0603 (module-level once-only guard)
    if _installed:
        return
    _installed = True

    processor = _TimingProcessor()
    provider = TracerProvider()
    provider.add_span_processor(processor)
    trace_api.set_tracer_provider(provider)
    _patch_stream_first_token()
    atexit.register(_flush, processor)


def _patch_stream_first_token() -> None:
    """Mark each Anthropic stream's first content_block_delta as a span event.

    `AnthropicInstrumentor` wraps every streaming response in its
    `AnthropicStream` proxy, whose `__next__` is the single path all stream
    consumption goes through (direct iteration, `text_stream`,
    `get_final_message`). The proxy holds the `anthropic.chat` span itself, so
    the event is attached to exactly the right span. Without the instrumentor
    there are no `anthropic.chat` spans at all, so there is nothing to patch.
    """
    try:
        # Lazy import: a missing instrumentor just disables the column
        from opentelemetry.instrumentation.anthropic.streaming import (  # noqa: PLC0415
            AnthropicStream,
        )
    except Exception:
        return

    orig_next = AnthropicStream.__next__

    def timed_next(self):  # noqa: ANN001, ANN202 (mirrors the proxy's signature)
        item = orig_next(self)
        if (
            not getattr(self, "_self_apollo_first_token_seen", False)
            and getattr(item, "type", "") == "content_block_delta"
        ):
            self._self_apollo_first_token_seen = True  # wrapt: stays on the proxy
            with contextlib.suppress(Exception):
                self._span.add_event(_FIRST_TOKEN_EVENT)
        return item

    AnthropicStream.__next__ = timed_next


def _fmt_s(ns: float) -> str:
    """Nanoseconds -> seconds string, more precision for short durations."""
    s = ns / 1e9
    return f"{s:.2f}s" if s < _PRECISE_BELOW_S else f"{s:.1f}s"


def _union_ns(intervals: list[tuple[int, int]]) -> int:
    """Total length of the union of (start, end) intervals, overlap counted once."""
    total = 0
    cur_start = cur_end = None
    for start, end in sorted(intervals):
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        elif end > cur_end:
            cur_end = end
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def _self_time_ns(record: _Record, children: list[_Record]) -> int:
    """Span duration minus the union of its children's intervals (clipped to it)."""
    start, end = record[0], record[1]
    clipped = [
        (max(cs, start), min(ce, end))
        for cs, ce, *_ in children
        if min(ce, end) > max(cs, start)
    ]
    return (end - start) - _union_ns(clipped)


def _bar(start: int, end: int, t0: int, total: int) -> str:
    """Fixed-width bar showing the span's position on the request wall-clock."""
    lo = round((start - t0) / total * _BAR_WIDTH)
    hi = round((end - t0) / total * _BAR_WIDTH)
    hi = max(hi, lo + 1)  # always visible
    return "▕" + " " * lo + "█" * (hi - lo) + " " * (_BAR_WIDTH - hi) + "▏"


def _axis(total: int) -> str:
    """Tick labels at 0/25/50/75/100% aligned to the bar column."""
    chars = [" "] * (_BAR_WIDTH + 2)
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        label = f"{total * frac / 1e9:.0f}s"
        pos = 1 + int(_BAR_WIDTH * frac) - (len(label) if frac == 1.0 else 0)
        for i, ch in enumerate(label):
            if 0 <= pos + i < len(chars):
                chars[pos + i] = ch
    return "".join(chars)


def _first_token_ns(record: _Record, marks: list[tuple[int, int]]) -> "int | None":
    """Time from this span's start to its stream's first token, or None.

    A mark belongs to this span when its timestamp falls inside the span and it
    was recorded on the span itself or on its direct parent (the `@observe`
    span current while the stream was consumed).
    """
    start, end, _, span_id, parent_id = record
    hits = [
        ts for owner, ts in marks
        if owner in (span_id, parent_id) and start <= ts <= end
    ]
    return min(hits) - start if hits else None


def _render(records: list[_Record], marks: "list[tuple[int, int]] | None" = None) -> str:
    """Build the waterfall + coverage-check text from raw span records."""
    marks = marks or []
    ids = {r[3] for r in records}
    children: dict[int, list[_Record]] = {}
    roots: list[_Record] = []
    for r in sorted(records, key=lambda r: r[0]):
        parent_id = r[4]
        if parent_id in ids:
            children.setdefault(parent_id, []).append(r)
        else:
            roots.append(r)

    t0 = min(r[0] for r in records)
    t1 = max(r[1] for r in records)
    total = max(t1 - t0, 1)

    # The planner's direct anthropic.chat children are its own LLM turns
    # (thinking + choosing the next tool call, or writing the final response);
    # label them so the waterfall doesn't need interpreting.
    display: dict[int, str] = {}
    for parent in records:
        if parent[2] != "planner":
            continue
        turns = [c for c in children.get(parent[3], []) if c[2] == "anthropic.chat"]
        for i, turn in enumerate(turns, 1):
            display[turn[3]] = f"anthropic.chat (planner turn {i}/{len(turns)})"

    rows: list[tuple[str, _Record, int, bool]] = []  # (label, record, self_ns, has_children)

    def walk(record: _Record, prefix: str, is_last: bool, top: bool) -> None:
        kids = children.get(record[3], [])
        name = display.get(record[3], record[2])
        rows.append((prefix + ("" if top else "└ " if is_last else "├ ") + name,
                     record, _self_time_ns(record, kids), bool(kids)))
        child_prefix = prefix if top else prefix + ("  " if is_last else "│ ")
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1, False)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1, True)

    name_width = max([len(label) for label, *_ in rows] + [len("span")]) + 2
    lines = [
        "",
        f"=== TIMING WATERFALL — total {_fmt_s(total)} ===",
        "indentation = ran inside parent; bars on the same horizontal range ran concurrently",
        "self = span time not covered by its child spans (leaf spans: self == total)",
        "anthropic.chat = one Anthropic API call, timed until its stream is fully consumed",
        "1st tok = model call start -> first streamed token"
        " ('-' = non-streaming call; services only stream when the payload sets stream: true)",
        "",
        f"{'span':<{name_width}} {'total':>8} {'self':>8} {'1st tok':>8}  {_axis(total)}",
    ]
    for label, record, self_ns, _ in rows:
        start, end = record[0], record[1]
        first_token = _first_token_ns(record, marks) if record[2] == "anthropic.chat" else None
        first_token_col = _fmt_s(first_token) if first_token is not None else (
            "-" if record[2] == "anthropic.chat" else ""
        )
        lines.append(
            f"{label:<{name_width}} {_fmt_s(end - start):>8} {_fmt_s(self_ns):>8} "
            f"{first_token_col:>8}  {_bar(start, end, t0, total)}",
        )

    lines += ["", "=== COVERAGE CHECK ==="]
    gaps = [(label.strip("│├└ "), record, self_ns)
            for label, record, self_ns, has_children in rows
            if has_children and self_ns > _GAP_THRESHOLD_NS]
    if gaps:
        lines.append("unmeasured time inside spans that have children (possible hidden slow steps):")
        for name, record, self_ns in sorted(gaps, key=lambda g: -g[2]):
            duration = record[1] - record[0]
            lines.append(
                f"  {name:<{name_width}} {_fmt_s(self_ns):>8}  "
                f"({self_ns / duration * 100:.0f}% of its {_fmt_s(duration)})",
            )
    else:
        lines.append("all spans with children are fully covered by them (<1s unmeasured each)")
    lines.append("======================")
    return "\n".join(lines) + "\n"


def _timing_file_path() -> "Path | None":
    """Where to save the timing text.

    `APOLLO_TIMING_FILE` (set per call by the acceptance harness) wins;
    otherwise derive a sibling of the run's `--output` file; None when neither
    is available (print-only).
    """
    env_path = os.environ.get("APOLLO_TIMING_FILE")
    if env_path:
        return Path(env_path)
    argv = sys.argv
    for flag in ("--output", "-o"):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                out = Path(argv[idx + 1])
                return out.with_name(out.stem + "_timing.txt")
    return None


def _flush(processor: _TimingProcessor) -> None:
    """Print the waterfall to stderr at exit, and save it next to --output."""
    if not processor.records:
        return
    text = _render(processor.records, processor.first_token_marks)
    sys.stderr.write(text)
    sys.stderr.flush()
    path = _timing_file_path()
    if path is None:
        return
    try:
        path.write_text(text)
        sys.stderr.write(f"timing saved to {path}\n")
    except OSError:
        pass
