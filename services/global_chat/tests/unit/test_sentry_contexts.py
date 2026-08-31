"""Nothing attached to a Sentry event may carry the user's job code.

`mask_secrets` matches credential field names and key-shaped values and has no
notion of job code, so the payload sailed through it untouched — and
`set_context` persists on the isolation scope, so one chat request would attach
its workflow to every later event in the process.
"""

import ast
import inspect

import pytest
from global_chat import planner as planner_module
from job_chat import job_chat as job_chat_module
from langfuse_util import CODE_BEARING_FIELDS, drop_code
from workflow_chat import workflow_chat as workflow_chat_module

SECRET_CODE = "const API_KEY = 'sk-live-do-not-log-me';"

#: Every module that attaches the incoming request to a Sentry event. This test
#: covered `workflow_chat` alone while `job_chat` carried a call site with the
#: same shape one directory over, which is how the last four rounds of this leak
#: went: the fix landed on the module someone happened to be reading.
REQUEST_CONTEXT_MODULES = [job_chat_module, workflow_chat_module]

#: Every module that calls `set_context` at all.
CONTEXT_MODULES = [job_chat_module, planner_module, workflow_chat_module]


def _module_id(module: object) -> str:
    return getattr(module, "__name__", str(module))


def _callee_name(func: ast.expr) -> str | None:
    """The bare function name, whether it is called plain or off a module."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


@pytest.mark.parametrize("field", sorted(CODE_BEARING_FIELDS))
def test_every_code_bearing_field_is_withheld(field: str) -> None:
    scrubbed = drop_code({field: SECRET_CODE})

    assert SECRET_CODE not in str(scrubbed)
    assert "withheld" in str(scrubbed[field])


def test_the_field_name_and_size_survive() -> None:
    """An operator needs to tell one failure from another; that needs the shape,
    not the content."""
    scrubbed = drop_code({"existing_yaml": "a" * 40})

    assert scrubbed["existing_yaml"] == "<40 characters withheld>"


def test_it_reaches_nested_and_listed_values() -> None:
    payload = {"meta": {"history": [{"content": SECRET_CODE}]}, "jobs": [{"body": SECRET_CODE}]}

    assert SECRET_CODE not in str(drop_code(payload))


def test_it_leaves_everything_else_alone() -> None:
    payload = {"meta": {"session_id": "abc", "user": {"id": 7}}, "adaptor": "@openfn/language-http"}

    assert drop_code(payload) == payload


def test_a_cyclic_payload_terminates() -> None:
    payload: dict = {"meta": {}}
    payload["meta"]["self"] = payload

    drop_code(payload)


def _set_context_calls(module: object) -> list[ast.Call]:
    tree = ast.parse(inspect.getsource(module))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node.func) == "set_context"
    ]


@pytest.mark.parametrize("module", REQUEST_CONTEXT_MODULES, ids=_module_id)
def test_the_request_context_is_scrubbed_before_it_is_attached(module: object) -> None:
    """Guards the call site, not just the helper.

    Matched against the parsed tree rather than the source text, so reformatting
    the call site cannot turn this green or red on its own.
    """
    attachments = [
        call
        for call in _set_context_calls(module)
        if call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "request_data"
    ]

    assert attachments, "no set_context('request_data', ...) call to guard"
    for call in attachments:
        assert len(call.args) > 1, "request_data attached with no value"
        value = call.args[1]
        assert isinstance(value, ast.Call) and _callee_name(value.func) == "drop_code", (
            "the request context is attached without drop_code"
        )


@pytest.mark.parametrize("module", CONTEXT_MODULES, ids=_module_id)
def test_no_context_names_a_code_bearing_field_without_the_scrubber(module: object) -> None:
    """`request_data` is not the only context that carries the job body.

    `job_chat` attaches `code_edit_context` with `llm_text_answer` and
    `llm_edit_answer` in it, both of which are the model's answer about the
    user's job. Naming the field is enough to require the scrubber, so a new
    context has to opt in rather than be remembered.
    """
    for call in _set_context_calls(module):
        payloads = [node for node in ast.walk(call) if isinstance(node, ast.Dict)]
        named = {
            key.value
            for payload in payloads
            for key in payload.keys
            if isinstance(key, ast.Constant) and key.value in CODE_BEARING_FIELDS
        }
        if not named:
            continue
        scrubbed = any(
            isinstance(node, ast.Call) and _callee_name(node.func) in {"drop_code", "mask_secrets"}
            for node in ast.walk(call)
        )
        assert scrubbed, (
            f"set_context at line {call.lineno} attaches {sorted(named)} without drop_code"
        )
