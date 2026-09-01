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
from unittest import mock

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
#: reason.
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
#: Removed as a SUBSTRING, exactly like `SANCTIONED`. Skipping the whole line
#: instead made `logger.info(f"body {len(body)} chars: {body[:100]}")`
#: invisible, and gave a real job-code leak in `job_chat.py` a permanent pass.
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



# --- default-deny inside a sink call ------------------------------------------
#
# Everything above this line is a denylist: thirteen identifiers in
# `CODE_BEARING_NAMES`, a handful of exception spellings. A leak escapes a
# denylist by picking a fourteenth name. `logger.info(f"Corrector response:
# {response}")` put the corrector's verbatim slice of the user's job body on the
# log and every pattern above walked straight past it, because the name was
# `response` and not `response_text`. `.get("corrected_new_code")` slipped
# through the mapping pattern for the same reason: the pattern only matches when
# the quoted key *begins* with a listed name.
#
# So inside a sink call the rule is inverted. An interpolation is allowed only
# if it is safe by construction, and anything else is a finding. Adding a
# fourteenth name to the denylist buys nothing; this asks instead what the
# expression can possibly evaluate to.

#: Calls whose result describes a value without reproducing it.
SAFE_CALLS = frozenset({"len", "bool", "id"})

#: The scrubbers. `drop_code(x)` has already withheld `x` by the time the sink
#: sees it, so it is the fix rather than the leak.
SCRUBBER_CALLS = frozenset({"drop_code", "mask_secrets"})

#: Calls that can only return a number, used to work out which locals hold a
#: size, a counter or a duration. `type(x).__name__` is handled separately.
NUMBER_CALLS = frozenset({"len", "int", "float", "sum", "ord", "abs", "round"})
NUMBER_METHODS = frozenset({
    "count", "index", "find", "rfind", "bit_length",
    # The clocks. `duration = time.time() - start` is the other shape a
    # shape-only log line comes in.
    "time", "perf_counter", "monotonic", "total_seconds",
})

#: The interpolations that were already on the log when the rule above was
#: inverted, reviewed one at a time and cleared. Keyed by module and matched on
#: the expression exactly as `ast.unparse` writes it, so renaming the variable,
#: moving the line to another module or reaching one level further down an
#: attribute chain all fail closed and come back here.
#:
#: This is the only way past the allowlist other than a whole-line
#: `safe-error-text:` marker, and it is deliberately narrower than one: it
#: clears a single expression rather than handing a line a pass from every
#: pattern in the file. Nothing here is the caller's content or the model's
#: prose about it. Those were fixed instead.
VETTED_INTERPOLATIONS: dict[str, frozenset[str]] = {
    # Command-line arguments, printed by the operator's own shell invocation.
    "entry.py": frozenset({"args.output", "args.port", "args.service"}),

    # `ApolloError.code` is the HTTP status we chose.
    "global_chat/global_chat.py": frozenset({"e.code"}),

    # Configured model id; Anthropic's `stop_reason`; the names of our own tool
    # definitions; and the job key, which names a node in the workflow and is
    # what correlates a log line with the request that produced it. A key is a
    # name the user typed into a form, never a job body.
    "global_chat/planner.py": frozenset({
        "self.model",
        "response.stop_reason",
        "stop_reason",
        "tool_use_block.name",
        "[b.name for b in tool_use_blocks]",
        "matched_job_key",
    }),

    # Routing metadata: the destination the router picked, its confidence, the
    # page the request came from, and the job key. `reason` is built a few lines
    # up out of literals and `list(parsed.keys())` — the client document's key
    # names, deliberately never its values, because a PyYAML mark quotes the
    # document. `from_agent` is one of two literals at the two call sites.
    "global_chat/router.py": frozenset({
        "self.model",
        "decision.confidence",
        "decision.destination",
        "decision.job_key",
        "router_job_key",
        "page",
        "reason",
        "from_agent",
    }),

    # The job key and the adaptor specifier. `drop_code` leaves `adaptor` alone
    # for the same reason: a package name is not the user's code.
    "global_chat/subagent_caller.py": frozenset({"job_key", "job_data['adaptor']"}),

    # `error_message` is one of the three literals `apply_single_edit` sets, and
    # `correction_warning` is `try_error_correction`'s third return, which is a
    # literal or a character count at every one of its four exits. Between them
    # they are the whole of the `warning` that becomes the Sentry issue title.
    # The token counts are integers from the API response.
    "job_chat/job_chat.py": frozenset({
        "error_message",
        "correction_warning",
        "message.usage.cache_creation_input_tokens",
        "message.usage.cache_read_input_tokens",
    }),

    # The adaptor package and version the job declares.
    "job_chat/old_prompt.py": frozenset({"adaptor.specifier"}),
    "job_chat/prompt.py": frozenset({"adaptor.specifier"}),
    "load_adaptor_docs/load_adaptor_docs.py": frozenset({
        "adaptor.specifier", "adaptor_spec.specifier",
    }),
    "latest_adaptors/latest_adaptors.py": frozenset({"package_name", "packages_url"}),

    # The adaptor, the query mode, and the adaptor function being fetched. All
    # of them describe the docs lookup, none of them touch the workflow.
    "search_adaptor_docs/search_adaptor_docs.py": frozenset({
        "adaptor.specifier",
        "format",
        "query_type",
        "function_name",
        "load_result.get('functions_uploaded', 0)",
    }),

    # The Pinecone namespace, and the names of the required fields a request
    # left out — field names from a literal list, not the values.
    "search_docsite/search_docsite.py": frozenset({
        "most_recent_namespace", "', '.join(missing)", "', '.join(missing_keys)",
    }),

    # The SSE transport itself rather than a log, and already masked. See the
    # comment on `_emit_event`: this is a third way out to the caller, so it
    # carries its own mask.
    "streaming_util.py": frozenset({"event_type", "json.dumps(mask_secrets(data))"}),

    # Job and edge names before and after sanitising, the adaptor a job
    # declares, and the `__ID_JOB_x__` placeholders this service invented
    # itself. Names and ids, never a body.
    # The naming work replaced per-key logging with one line naming the whole
    # renamed set, so the individual key expressions the leak branch vets are
    # gone from this module here.
    "workflow_chat/workflow_chat.py": frozenset({
        "adaptor",
        "job_key",
        "current_id",
        # Job names and edge endpoints, resolved or unresolved. `unclaimed`
        # reads as bodies but holds the `__CODE_BLOCK_<key>__` tokens, so it is
        # keys too. Same category as the names above, and the reason a name is
        # loggable where a body is not: the user typed it into a form as a
        # label, and a log line is unreadable without it.
        "', '.join(sorted(matches))",
        "', '.join(duplicated)",
        "', '.join(unclaimed)",
        "', '.join(renamed)",
        "by_name",
        "owner",
        "', '.join(sorted(dangling))",
        # Literals chosen at the call site, a parameter the callers pass a
        # literal to, and a count. `msg` is built but only from `len()`.
        "how",
        "label",
        "msg",
        # More names: the reference as written, and what it sanitises to.
        "reference",
        "str(reference)",
        "resolved",
    }),

    # Job names again, on the shared walkers.
    "yaml_utils.py": frozenset({
        "', '.join(sorted((str(match) for match in matches)))",
        "job_key",
        "how",
        "step_name",
    }),
}


#: Callees that put a value outside the process. Kept in step with `SINKS`,
#: which is the same list expressed for a line-at-a-time scan.
SINK_CALLEES = frozenset({
    "capture_message", "capture_exception", "set_context", "set_extra",
    "set_tag", "add_breadcrumb", "print",
})


def _callee_name(func: ast.expr) -> str | None:
    """The bare function name, whether it is called plain or off an object."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_sink_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
            and func.value.id.endswith("logger"):
        return True
    return _callee_name(func) in SINK_CALLEES


def _is_int_expression(node: ast.expr, known: set[str]) -> bool:  # noqa: PLR0911 - one return per node kind
    """True when the expression can only evaluate to a number."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, int) and not isinstance(node.value, bool)
    if isinstance(node, ast.Name):
        return node.id in known
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in NUMBER_CALLS
        if isinstance(func, ast.Attribute):
            return func.attr in NUMBER_METHODS
        return False
    if isinstance(node, ast.BinOp):
        return _is_int_expression(node.left, known) and _is_int_expression(node.right, known)
    if isinstance(node, ast.UnaryOp):
        return _is_int_expression(node.operand, known)
    if isinstance(node, ast.IfExp):
        return _is_int_expression(node.body, known) and _is_int_expression(node.orelse, known)
    return False


def _int_valued_names(tree: ast.AST) -> set[str]:
    """Locals that only ever hold a number.

    A counter or a size is the one bare name that is safe to interpolate, and
    the shape-only log lines this guard is meant to encourage are written with
    them. Every assignment to the name in the module has to qualify, so one
    `total = response_text` elsewhere disqualifies `total` everywhere.
    """
    assignments: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if isinstance(node.target, ast.Name) and node.value is not None:
                assignments.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            # `for attempt in range(...)` binds a counter, which is the other
            # place a safe interpolation comes from.
            over_range = isinstance(node.iter, ast.Call) \
                and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range"
            assignments.setdefault(node.target.id, []).append(
                ast.Constant(value=0) if over_range else node.iter,
            )

    known: set[str] = set()
    for _ in range(len(assignments) + 1):
        grew = False
        for name, values in assignments.items():
            if name in known:
                continue
            if all(_is_int_expression(value, known) for value in values):
                known.add(name)
                grew = True
        if not grew:
            break
    return known


def _is_safe_interpolation(  # noqa: PLR0911 - one return per allowlist entry
    node: ast.expr, int_names: set[str], vetted: frozenset[str],
) -> bool:
    """The whole allowlist. Everything not named here is a finding."""
    if isinstance(node, ast.Constant):
        # A literal cannot carry anything the caller sent.
        return True
    if isinstance(node, ast.Name):
        return node.id in int_names or node.id in vetted
    if isinstance(node, ast.Attribute):
        # `type(e).__name__`, and the same for a class or a function.
        return node.attr == "__name__" or ast.unparse(node) in vetted
    if isinstance(node, ast.Call):
        if _callee_name(node.func) in SAFE_CALLS | SCRUBBER_CALLS:
            return True
        return ast.unparse(node) in vetted
    if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.IfExp)):
        return _is_int_expression(node, int_names) or ast.unparse(node) in vetted
    return ast.unparse(node) in vetted


def _interpolations(node: ast.AST) -> list[ast.FormattedValue]:
    """Every `{...}` under `node`, not descending into a scrubbed subtree."""
    found: list[ast.FormattedValue] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current is not node and isinstance(current, ast.Call) \
                and _callee_name(current.func) in SCRUBBER_CALLS:
            continue
        if isinstance(current, ast.FormattedValue):
            found.append(current)
        stack.extend(ast.iter_child_nodes(current))
    return found


def _unvetted_part(value: ast.expr, int_names: set[str], vetted: frozenset[str]) -> str | None:
    """The first unvetted thing this expression builds a string out of.

    An f-string or a concatenation assigned to a name, then handed to a sink on
    a later line, defeated every pattern above: the code patterns only run on
    lines inside a sink call, and the sink line carries nothing but a bare name.
    `warning = f"...{corrected_new_code}"` followed by `logger.warning(warning)`
    is the exact shape that reached Sentry as an issue title.
    """
    if isinstance(value, ast.JoinedStr):
        for part in value.values:
            if isinstance(part, ast.FormattedValue) \
                    and not _is_safe_interpolation(part.value, int_names, vetted):
                return ast.unparse(part.value)
        return None
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
        return _unvetted_part(value.left, int_names, vetted) \
            or _unvetted_part(value.right, int_names, vetted)
    if isinstance(value, ast.IfExp):
        return _unvetted_part(value.body, int_names, vetted) \
            or _unvetted_part(value.orelse, int_names, vetted)
    if isinstance(value, ast.Constant):
        return None
    # A bare name, a call, an attribute: the operand of a concatenation that
    # nobody has vetted. `"failed: " + error_message` is how this starts.
    return None if _is_safe_interpolation(value, int_names, vetted) else ast.unparse(value)


def _text_assignments(
    tree: ast.AST, int_names: set[str], vetted: frozenset[str],
) -> dict[str, list[tuple[int, str | None]]]:
    """Every assignment of a name to a built string: line, and whether unvetted.

    Both halves matter. `msg` is assigned a leaky f-string in one branch of
    `prompt.py` and a `type(e).__name__` one in the next, and only the first
    should carry to the `logger.warning(msg)` under it, so the *nearest
    preceding* assignment is what decides.

    One hop only. `b = a` where `a` was built from a secret is not tracked, so
    `logger.warning(b)` passes. Chasing arbitrary alias chains costs more than
    it buys here, since every leak found so far has been direct or one hop, but
    the gap is real and this is where to close it if a second hop ever turns up.
    """
    assignments: dict[str, list[tuple[int, str | None]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            unvetted = None
            if isinstance(node.value, (ast.JoinedStr, ast.BinOp, ast.IfExp)):
                unvetted = _unvetted_part(node.value, int_names, vetted)
            assignments.setdefault(target.id, []).append((node.lineno, unvetted))
    return {name: sorted(entries, key=lambda e: e[0]) for name, entries in assignments.items()}


def _reaches_sink_unvetted(
    name: str, line: int, assignments: dict[str, list[tuple[int, str | None]]],
) -> tuple[int, str] | None:
    """The assignment that makes `name` unsafe at `line`, and what made it so."""
    entries = assignments.get(name)
    if not entries:
        return None
    before = [entry for entry in entries if entry[0] < line]
    if before:
        assigned_at, unvetted = before[-1]
        return (assigned_at, unvetted) if unvetted else None
    # Nothing precedes the sink, so this is a loop or a closure. Stay
    # conservative and take any unvetted assignment to the name.
    return next(((at, part) for at, part in entries if part), None)


def _sink_findings(module: str, source: str) -> list[tuple[int, str]]:
    """Everything a sink call interpolates or is handed that is not vetted."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
        return []
    vetted = VETTED_INTERPOLATIONS.get(module, frozenset())
    int_names = _int_valued_names(tree)
    assignments = _text_assignments(tree, int_names, vetted)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_sink_call(node):
            continue
        for part in _interpolations(node):
            if _is_safe_interpolation(part.value, int_names, vetted):
                continue
            line = min(max(part.lineno, node.lineno), node.end_lineno or part.lineno)
            found.append((line, f"unvetted interpolation `{ast.unparse(part.value)}`"))
        arguments = list(node.args) + [keyword.value for keyword in node.keywords]
        for argument in arguments:
            if not isinstance(argument, ast.Name):
                continue
            reached = _reaches_sink_unvetted(argument.id, node.lineno, assignments)
            if reached is not None:
                assigned_at, unvetted = reached
                found.append((
                    node.lineno,
                    f"`{argument.id}` carries unvetted `{unvetted}` from line {assigned_at}",
                ))
    return found


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


def _scan_source(module: str, source: str) -> list[str]:
    """The whole guard, over one module's text. Split out from `_scan` so the
    tests below can hand it a three-line sample instead of a file."""
    patterns = _leak_patterns(_exception_names(source)) + _code_patterns()
    docstrings = _docstring_lines(source)
    sink_lines = _sink_lines(source) - _call_lines(source, SCRUBBED)
    lines = source.split("\n")
    findings: dict[int, str] = {}
    for number, line in enumerate(lines, 1):
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
                findings[number] = f"{module}:{number} [{label}] {stripped[:80]}"
                break

    for number, label in _sink_findings(module, source):
        if number in findings or not 1 <= number <= len(lines):
            continue
        if MARKER.search(lines[number - 1]):
            continue
        findings[number] = f"{module}:{number} [{label}] {lines[number - 1].strip()[:80]}"

    return [findings[number] for number in sorted(findings)]


def _scan(module: str) -> list[str]:
    return _scan_source(module, (SERVICES / module).read_text())


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
    """`f"{type(e).__name__}: {e}"` is exactly what someone writes once the
    guard has taught them the safe token."""
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
    """`DESCRIBED` used to skip the whole line, which gave any line containing
    `len(...)` a permanent pass."""
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


# --- the default-deny half ----------------------------------------------------

#: The four shapes that were on the log when this rule was written, all of which
#: the denylist above reported nothing for.
LEAK_SAMPLES = {
    "a raw model reply under an unlisted name":
        'logger.info(f"Corrector response: {response}")',
    "a mapping lookup whose key is not a listed prefix":
        """logger.warning(f"Tried to apply: {correction_data.get('corrected_new_code')}")""",
    "a slice of the client's chat message":
        'logger.info(f"called with content: {data.content[:100]}...")',
    "a preview of a subagent's reply":
        'logger.info(f"workflow_agent response: {response_preview}")',
}


@pytest.mark.parametrize("shape", sorted(LEAK_SAMPLES))
def test_the_allowlist_catches_a_leak_the_denylist_missed(shape: str) -> None:
    """`CODE_BEARING_NAMES` is thirteen identifiers, so a leak escapes it by
    picking a fourteenth. Every sample here did exactly that."""
    findings = _scan_source("sample.py", LEAK_SAMPLES[shape] + "\n")

    assert findings, shape


def test_the_allowlist_permits_a_shape_only_line() -> None:
    source = (
        "count = len(body)\n"
        'logger.info(f"body: {len(body)} characters, {count} of them, "\n'
        '            f"empty: {bool(body)} ({type(body).__name__})")\n'
    )

    assert not _scan_source("sample.py", source)


def test_an_assignment_hop_does_not_hide_a_leak() -> None:
    """The whole of weakness (a): the code patterns only run on lines inside a
    sink call, and the sink line carries nothing but a bare name."""
    source = (
        'warning = f"Tried to apply: {corrected_new_code}"\n'
        "logger.warning(warning)\n"
    )

    findings = _scan_source("sample.py", source)

    assert findings
    assert "corrected_new_code" in findings[0]


def test_a_concatenation_hop_does_not_hide_a_leak_either() -> None:
    source = 'warning = "Initial error: " + error_message\nsentry_sdk.capture_message(warning)\n'

    assert _scan_source("sample.py", source)


def test_the_nearest_assignment_is_what_decides() -> None:
    """`msg` is built leakily in one branch and safely in the next. Only the
    first should carry to the sink under it, or every later branch inherits a
    finding it did not earn."""
    source = (
        'msg = f"failed: {body}"\n'
        "logger.warning(msg)\n"
        'msg = f"failed ({type(error).__name__})"\n'
        "logger.warning(msg)\n"
    )

    findings = _scan_source("sample.py", source)

    assert [f.split(":")[1].split(" ")[0] for f in findings] == ["2"]


def test_a_counter_is_the_one_bare_name_that_passes() -> None:
    source = (
        "total = 0\n"
        "for attempt in range(3):\n"
        "    total += 1\n"
        '    logger.info(f"attempt {attempt + 1}, {total} so far")\n'
    )

    assert not _scan_source("sample.py", source)


def test_a_counter_that_is_ever_a_string_is_not_a_counter() -> None:
    """One `total = response_text` anywhere in the module disqualifies the name
    everywhere, because this guard has no idea which branch ran."""
    source = (
        "total = 0\n"
        "total = response_text\n"
        'logger.info(f"{total}")\n'
    )

    assert _scan_source("sample.py", source)


def test_a_vetted_expression_is_scoped_to_its_module() -> None:
    """Renaming a variable or moving the line elsewhere has to fail closed."""
    line = 'logger.info(f"model: {self.model}")\n'

    assert not _scan_source("global_chat/planner.py", line)
    assert _scan_source("job_chat/job_chat.py", line)


#: Every expression cleared by hand in `VETTED_INTERPOLATIONS`. Pinned for the
#: same reason as `EXPECTED_MARKERS`: an opt-out nobody counts is an opt-out
#: that spreads.
EXPECTED_VETTED_INTERPOLATIONS = 60


def test_the_vetted_interpolations_are_inventoried() -> None:
    total = sum(len(expressions) for expressions in VETTED_INTERPOLATIONS.values())

    assert total == EXPECTED_VETTED_INTERPOLATIONS, (
        f"the hand-cleared expression list changed to {total}. Each entry is a "
        f"value this codebase puts on the log, so add one deliberately."
    )


@pytest.mark.parametrize("module", sorted(VETTED_INTERPOLATIONS))
def test_every_vetted_module_is_still_on_the_chat_path(module: str) -> None:
    assert module in CHAT_PATH_MODULES


@pytest.mark.parametrize(
    ("module", "expression"),
    [(m, e) for m, es in sorted(VETTED_INTERPOLATIONS.items()) for e in sorted(es)],
)
def test_no_vetted_expression_is_dead(module: str, expression: str) -> None:
    """A cleared expression that nothing writes any more is a pass sitting there
    waiting for someone to reintroduce the name."""
    narrowed = dict(VETTED_INTERPOLATIONS)
    narrowed[module] = VETTED_INTERPOLATIONS[module] - {expression}

    with mock.patch.dict(VETTED_INTERPOLATIONS, narrowed, clear=True):
        findings = _scan(module)

    assert findings, f"{module} no longer interpolates {expression}"


def test_package_inits_are_in_the_closure() -> None:
    """Resolution matches `pkg/submodule.py` before `pkg/__init__.py`, so an
    init would otherwise never be scanned."""
    inits = [m for m in CHAT_PATH_MODULES if m.endswith("__init__.py")]

    assert inits
    assert "workflow_chat/__init__.py" in inits
    assert len(inits) == len(set(inits))
