"""No client content on the log or the error payload, across the chat path.

The bridge forwards every Python log line to the caller as an SSE `log` event
(`platform/src/bridge.ts`), and an `ApolloError` message is returned as the
error body. So neither is an operator-only channel. The masking filter is no
defence: it redacts by credential field name and `sk-` value shape, and it
rewrites `record.msg`, never `exc_text`.

The guard below is a source scan rather than a behavioural test because this
leak has reappeared under a new name in four separate rounds, each time as the
sibling of the site that had just been fixed. Catching it at the point it is
written is the only thing that has worked.
"""

import ast
import logging
import re
from pathlib import Path

import pytest
import yaml
from global_chat import global_chat as global_chat_module
from util import ApolloError

SERVICES = Path(__file__).resolve().parents[3]

#: The entry points a request can arrive at.
CHAT_ENTRY_POINTS = [
    "global_chat/global_chat.py",
    "workflow_chat/workflow_chat.py",
    "job_chat/job_chat.py",
]


def _resolve_import(name: str, package: str) -> Path | None:
    candidates = [
        SERVICES / (name.replace(".", "/") + ".py"),
        SERVICES / name.replace(".", "/") / "__init__.py",
    ]
    if package:
        candidates += [
            SERVICES / package / (name.replace(".", "/") + ".py"),
            SERVICES / package / name.replace(".", "/") / "__init__.py",
        ]
    return next((c for c in candidates if c.exists()), None)


def _import_closure(entries: list[str]) -> list[str]:
    """Every module reachable from `entries`, following relative imports too.

    Derived rather than hand-listed. Six times now a leak has been fixed in one
    module while its twin sat one import hop away, unlisted — `old_prompt.py`
    is the DEFAULT job_chat path and was absent while `prompt.py` was being
    repaired line by line. A hand-maintained list encodes what the last person
    happened to look at; this encodes what a request can actually reach.

    A package's `__init__.py` is pulled in alongside its submodules. Resolution
    matches `pkg/submodule.py` before `pkg/__init__.py`, so the init would
    otherwise never enter the closure — no `__init__.py` under `services/`
    holds executable code today, so nothing was unscanned, but that is a
    property of the tree rather than of this function.
    """
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        relative = stack.pop()
        if relative in seen:
            continue
        path = SERVICES / relative
        if not path.exists():
            continue
        seen.add(relative)
        package = str(Path(relative).parent) if Path(relative).parent != Path() else ""
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else [a.name for a in node.names]
            for name in names:
                resolved = _resolve_import(name, package)
                if not resolved:
                    continue
                stack.append(str(resolved.relative_to(SERVICES)))
                # ...and every package `__init__.py` on the way to it.
                for parent in resolved.relative_to(SERVICES).parents:
                    init = SERVICES / parent / "__init__.py"
                    if init.exists():
                        stack.append(str(init.relative_to(SERVICES)))
    return sorted(seen)


#: Everything a request can reach, plus `entry.py`, which wraps every call.
CHAT_PATH_MODULES = sorted({*_import_closure(CHAT_ENTRY_POINTS), "entry.py"})


#: Names an exception is conventionally bound to. `_any` also catches a
#: non-conventional binding by looking at what the `except ... as` clause bound.
_EXC = r"(?:e|err|error|exc|exception|ex)"

#: The sanctioned constructs. Removed from the line *as substrings* before the
#: leak patterns run, so they exempt themselves and nothing else. Matching them
#: against the whole line and skipping it is what let
#: `logger.error(f"{type(e).__name__}: {e}")` through with no marker at all —
#: which is precisely the shape a developer reaches for once the guard has
#: taught them the safe token.
SANCTIONED = [
    re.compile(r"type\(\s*\w+\s*\)\.__name__"),
    re.compile(r"str\(\s*\w+\.__cause__\s*\)"),
]

#: An explicit, reasoned opt-out for a whole line. Unlike the constructs above
#: this does skip the line, so every use is inventoried below and must carry a
#: reason — an opt-out nobody counts is an opt-out that spreads.
MARKER = re.compile(r"#\s*safe-error-text:")


def _strip_sanctioned(line: str) -> str:
    """Remove the safe constructs, leaving whatever else the line does."""
    for pattern in SANCTIONED:
        line = pattern.sub("", line)
    return line


def _docstring_lines(source: str) -> set[int]:
    """Line numbers occupied by docstrings, which are prose and not code."""
    occupied: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return occupied
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            occupied.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return occupied


def _exception_names(source: str) -> set[str]:
    """Every name an `except ... as NAME` clause binds in this module."""
    names = set(re.findall(r"except[^\n]*\bas\s+(\w+)\s*:", source))
    return names or {"e"}


#: Variables that hold the user's job code or workflow. The patterns below
#: modelled *exception* text only, which is the other half of the scope
#: problem: `logger.info(f"old code: {old_code}")` logged a verbatim slice of
#: the body and every pattern walked past it, because it is not an exception.
CODE_BEARING_NAMES = (
    "old_code", "new_code", "suggested_code", "code", "body", "expression",
    "prompt", "text_answer", "workflow_yaml", "existing_yaml", "response_text",
    "edit", "content",
)


#: The subset of the above that cannot plausibly appear as English in a log
#: message. Used for the bare-name pattern, where there is no `{...}` or sink
#: text on the line to anchor against.
CODE_VARIABLE_NAMES = (
    "old_code", "new_code", "suggested_code", "workflow_yaml", "existing_yaml",
    "response_text", "text_answer",
)


#: Where a value becomes visible outside the process. Putting job code into a
#: *prompt* is the whole point of this service, so the code patterns apply only
#: to lines that reach one of these.
SINKS = re.compile(
    r"logger\.\w+\s*\("
    r"|capture_message\s*\("
    r"|capture_exception\s*\("
    r"|set_context\s*\("
    r"|set_extra\s*\("
    r"|set_tag\s*\("
    r"|add_breadcrumb\s*\("
    r"|\bprint\s*\(",
)

#: `len(x)` and `type(x)` describe a value without reproducing it.
#:
#: Removed as a SUBSTRING, exactly like `SANCTIONED`. It used to skip the whole
#: line, which is the defect `SANCTIONED` was restructured to remove one rule
#: over: `logger.info(f"body {len(body)} chars: {body[:100]}")` was invisible,
#: and `job_chat.py:648` — a verbatim job-code leak one round ago — contains
#: `len(old_code` and so had a permanent pass. Same shape, one round apart.
DESCRIBED = re.compile(r"(?:len|type|bool|id)\([^()]*\)")


def _code_patterns() -> list:
    names = "(?:" + "|".join(CODE_BEARING_NAMES) + ")"
    return [
        ("code on a log or Sentry line",
         re.compile(r"\{\s*" + names + r"\s*(?:\[[^\]]*\]|\.\w+|\.get\([^)]*\))*\s*[:!}]")),
        ("code as a sink argument",
         re.compile(r"(?:" + SINKS.pattern + r")[^)]*\b" + names + r"\s*(?:\[[^\]]*\]|\.\w+)*\s*[,)]")),
        # A sink call wrapped across lines puts the value on a line with no
        # sink text on it, so the two patterns above cannot see it. Only the
        # unambiguous variable names are used here: `content`, `prompt` and
        # `edit` are ordinary English and would fire inside message text.
        ("code named on a sink continuation line",
         re.compile(r"(?<![\w\"'])(?:" + "|".join(CODE_VARIABLE_NAMES) + r")\b(?![\"'\w])")),
        ("code reached through a mapping",
         re.compile(r"\.get\(\s*[\"']" + names + r"[\"']")),
    ]


def _leak_patterns(names: set[str]) -> list:
    bound = "(?:" + "|".join([*sorted(re.escape(n) for n in names), _EXC]) + ")"
    return [
        # A traceback goes into `exc_text`, which the masking filter never
        # touches. This is the vector `yaml_utils` names in its own comments.
        ("logger.exception", re.compile(r"logger\.exception\s*\(")),
        ("exc_info", re.compile(r"exc_info\s*=")),
        ("traceback.format_exc", re.compile(r"traceback\.format_exc\s*\(")),
        ("exception in an f-string", re.compile(r"\{\s*(?:str\(|repr\()?" + bound + r"\)?\s*(?:!r|!s)?\s*[:}]")),
        ("exception as a bare arg", re.compile(r"[\"']\s*,\s*" + bound + r"\s*[,)]")),
        ("logger.x(e)", re.compile(r"logger\.\w+\s*\(\s*" + bound + r"\s*[,)]")),
        ("exception concatenated", re.compile(r"\+\s*(?:str|repr)\(\s*" + bound + r"\s*\)")),
        ("%-formatting", re.compile(r"%\s*(?:str\()?" + bound + r"\)?\b")),
        (".format(e)", re.compile(r"\.format\([^)]*\b" + bound + r"\b")),
        ("str(exception) in a payload", re.compile(r"\bstr\(\s*" + bound + r"\s*\)")),
        ("repr(exception)", re.compile(r"\brepr\(\s*" + bound + r"\s*\)")),
        ("exception .args", re.compile(r"\b" + bound + r"\.args\b")),
        ("exception .message", re.compile(r"\b" + bound + r"\.message\b")),
    ]


#: The scrubber. A value passed through it is withheld by the time it reaches
#: the sink, so `drop_code({"llm_text_answer": text_answer})` is the fix, not
#: the leak.
SCRUBBED = re.compile(r"drop_code\s*\(|mask_secrets\s*\(")


def _call_lines(source: str, opener: "re.Pattern[str]") -> set[int]:
    """Line numbers inside a call matching `opener`, continuations included."""
    inside: set[int] = set()
    depth = 0
    for number, line in enumerate(source.split("\n"), 1):
        opens = bool(opener.search(line))
        if depth > 0 or opens:
            inside.add(number)
            depth += line.count("(") - line.count(")")
            depth = max(depth, 0)
    return inside


def _sink_lines(source: str) -> set[int]:
    """Line numbers that sit inside a sink call, including continuations.

    `SINKS` matched one line at a time, so the second line of a wrapped
    `logger.info(...)` was not a sink line and its contents were never checked.
    That is where a slice of the job body would sit in a wrapped call.
    """
    inside: set[int] = set()
    depth = 0
    for number, line in enumerate(source.split("\n"), 1):
        if depth > 0:
            inside.add(number)
        elif SINKS.search(line):
            inside.add(number)
            depth = 0
        if SINKS.search(line) or depth > 0:
            depth += line.count("(") - line.count(")")
            depth = max(depth, 0)
    return inside


def _scan(module: str) -> list[str]:
    source = (SERVICES / module).read_text()
    patterns = _leak_patterns(_exception_names(source)) + _code_patterns()
    docstrings = _docstring_lines(source)
    sink_lines = _sink_lines(source) - _call_lines(source, SCRUBBED)
    findings = []
    for number, line in enumerate(source.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#") or number in docstrings:
            continue
        if MARKER.search(line):
            continue
        remainder = _strip_sanctioned(line)
        # A description of a value is not the value. Removed as a substring so
        # the rest of the line is still read.
        remainder = DESCRIBED.sub("", remainder)
        for label, pattern in patterns:
            # Prompt construction is not a leak; only what leaves the process is.
            if "code" in label and number not in sink_lines:
                continue
            if pattern.search(remainder):
                findings.append(f"{module}:{number} [{label}] {stripped[:80]}")
                break
    return findings


@pytest.mark.parametrize("module", CHAT_PATH_MODULES)
def test_no_module_puts_an_exception_on_a_caller_visible_channel(module: str) -> None:
    findings = _scan(module)

    assert not findings, "\n".join(
        ["exception text can reach the caller here; use type(e).__name__:", *findings],
    )


def test_the_guard_catches_each_leak_shape() -> None:
    """Guards the guard. Every pattern exists because a real leak used that
    shape and an earlier version of this guard missed it."""
    patterns = _leak_patterns({"e", "err", "problem"})
    samples = {
        "logger.exception": 'logger.exception("Error calling workflow_agent")',
        "exc_info": 'logger.error("failed", exc_info=True)',
        "traceback": 'logger.error(traceback.format_exc())',
        "f-string": 'logger.error(f"failed: {e}")',
        "f-string repr": 'logger.error(f"failed: {e!r}")',
        "bare arg": 'logger.error("failed: %s", e)',
        "logger.x(e)": "logger.error(e)",
        "concatenation": 'logger.error("failed: " + str(e))',
        "%-formatting": 'logger.error("failed: %s" % str(e))',
        ".format": 'logger.error("failed: {}".format(e))',
        "str() in a payload": "raise ApolloError(500, str(e))",
        "repr()": "raise ApolloError(500, repr(e))",
        ".args": 'logger.error(f"failed: {e.args[0]}")',
        ".message": 'logger.error(f"failed: {e.message}")',
        "non-conventional binding": 'logger.error(f"failed: {problem}")',
    }
    for shape, line in samples.items():
        assert any(p.search(_strip_sanctioned(line)) for _, p in patterns), shape


def test_a_safe_construct_does_not_exempt_the_rest_of_its_line() -> None:
    """The bug this guard had: matching the safe construct against the whole
    line and skipping it. `f"{type(e).__name__}: {e}"` is exactly what someone
    writes once the guard has taught them the safe token."""
    patterns = _leak_patterns({"e"})
    line = 'logger.error(f"{type(e).__name__}: {e}")'

    assert any(p.search(_strip_sanctioned(line)) for _, p in patterns)


def test_the_guard_permits_the_sanctioned_form() -> None:
    patterns = _leak_patterns({"e"})
    for line in (
        'logger.error(f"failed ({type(e).__name__})")',
        'raise ApolloError(500, f"failed ({type(e).__name__})")',
        'details={"cause": str(e.__cause__)}',
    ):
        assert not any(p.search(_strip_sanctioned(line)) for _, p in patterns), line


#: Shortest reason that counts as one. A bare "safe" is not a reason.
MIN_REASON_LENGTH = 10

#: Every line-level opt-out in the tree. Inventoried so the count cannot grow
#: quietly: an opt-out nobody counts is an opt-out that spreads.
EXPECTED_MARKERS = 5


def test_the_line_level_opt_outs_are_inventoried() -> None:
    marked = []
    for module in CHAT_PATH_MODULES:
        source = (SERVICES / module).read_text()
        for number, line in enumerate(source.split("\n"), 1):
            if MARKER.search(line) and not line.strip().startswith("#"):
                reason = line.split("safe-error-text:", 1)[1].strip()
                assert len(reason) > MIN_REASON_LENGTH, f"{module}:{number} opts out with no reason"
                marked.append(f"{module}:{number}")

    assert len(marked) == EXPECTED_MARKERS, (
        f"line-level opt-outs changed: {marked}. Each one hands a whole line a "
        f"pass, so update EXPECTED_MARKERS deliberately or narrow the code."
    )


# --- the behavioural half -----------------------------------------------------

#: A PyYAML error whose mark quotes the offending line. The tab is what makes
#: the scanner fail *on* the body line rather than after it.
SECRET_CODE = "const API_KEY = 'sk-live-do-not-log-me';"
SECRET_FRAGMENT = "sk-live-do-not-log-me"
LEAKY_DOCUMENT = f"jobs:\n  a:\n    body: {SECRET_CODE}\tx\n"


def _parse_error() -> Exception:
    try:
        yaml.safe_load(LEAKY_DOCUMENT)
    except Exception as error:
        return error
    raise AssertionError("the fixture document parsed; it no longer reproduces the leak")


def test_the_fixture_really_does_quote_the_document() -> None:
    """Guards the tests below: if PyYAML stops quoting, they prove nothing."""
    assert SECRET_FRAGMENT in str(_parse_error())


def test_the_real_global_chat_handler_logs_no_document_text(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calls the actual handler rather than rebuilding its log line.

    The previous version of this test built the safe string itself and then
    asserted the secret was absent from what it had just built, which is true
    of any string.
    """
    module = global_chat_module

    inner = _parse_error()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise ApolloError(500, f"workflow_agent failed ({type(inner).__name__})")

    monkeypatch.setattr(module, "RouterAgent", explode)

    with caplog.at_level(logging.ERROR), pytest.raises(ApolloError):
        module.main({"content": "hi", "api_key": "sk-ant-test"})

    assert SECRET_FRAGMENT not in caplog.text
    assert SECRET_CODE not in caplog.text


def test_an_apollo_error_carrying_document_text_is_still_not_logged(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adversarial case: something upstream *does* build a leaky message.

    The handler must not widen the blast radius by logging it.
    """
    module = global_chat_module

    def explode(*_args: object, **_kwargs: object) -> None:
        raise ApolloError(500, f"workflow_agent failed: {_parse_error()}")

    monkeypatch.setattr(module, "RouterAgent", explode)

    with caplog.at_level(logging.ERROR), pytest.raises(ApolloError):
        module.main({"content": "hi", "api_key": "sk-ant-test"})

    assert SECRET_FRAGMENT not in caplog.text


def test_a_described_value_does_not_exempt_the_rest_of_its_line() -> None:
    """`DESCRIBED` used to skip the whole line, which is the defect
    `SANCTIONED` was restructured to remove one rule over.

    `job_chat.py` contains `len(old_code` on a line that was a verbatim
    job-code leak one round earlier, so that line had a permanent pass.
    """
    patterns = _code_patterns()
    line = '''logger.info(f"body {len(body)} chars: {body[:100]}")'''

    remainder = DESCRIBED.sub("", _strip_sanctioned(line))
    assert any(p.search(remainder) for _, p in patterns)


def test_a_description_alone_is_still_permitted() -> None:
    patterns = _code_patterns()
    line = '''logger.info(f"body: {len(body)} characters")'''

    remainder = DESCRIBED.sub("", _strip_sanctioned(line))
    assert not any(p.search(remainder) for _, p in patterns)


def test_a_wrapped_sink_call_counts_as_a_sink_on_every_line() -> None:
    """`SINKS` matched one line at a time, so the second line of a wrapped
    `logger.info(...)` was never checked — which is where a slice of the job
    body would sit."""
    source = 'logger.info(\n    f"out: {len(old_code)}",\n    f"body: {old_code[:80]}",\n)\nx = 1\n'

    inside = _sink_lines(source)

    wrapped_call_lines = {1, 2, 3}
    line_after_the_call = 5

    assert wrapped_call_lines <= inside
    assert line_after_the_call not in inside


def test_the_scrubber_exempts_what_it_wraps() -> None:
    """A value passed through `drop_code` is withheld by the time it reaches
    the sink, so it is the fix rather than the leak."""
    source = 'sentry_sdk.set_context("x", drop_code({\n    "llm_text_answer": text_answer,\n}))\n'
    line_holding_the_value = 2

    assert line_holding_the_value in _call_lines(source, SCRUBBED)


def test_package_inits_are_in_the_closure() -> None:
    """Resolution matches `pkg/submodule.py` before `pkg/__init__.py`, so an
    init would otherwise never be scanned."""
    inits = [m for m in CHAT_PATH_MODULES if m.endswith("__init__.py")]

    assert inits
    assert "workflow_chat/__init__.py" in inits
    assert len(inits) == len(set(inits))
