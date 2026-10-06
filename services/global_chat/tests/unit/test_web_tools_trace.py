"""Unit tests for the web-tools trace builder (test helper, not production code)."""

from types import SimpleNamespace as Block

import pytest
from global_chat.tests.web_tools.trace import build_trace, count, format_trace

PATIENT = "https://hl7.org/fhir/R4/patient.html"


def use(block_id: str, name: str, **tool_input: str) -> Block:
    return Block(type="server_tool_use", id=block_id, name=name, input=tool_input)


def result(block_id: str, block_type: str, content: object) -> Block:
    return Block(type=block_type, tool_use_id=block_id, content=content)


def response(*blocks: Block) -> Block:
    return Block(content=list(blocks))


def fetched(text: str) -> Block:
    return Block(type="web_fetch_result", url=PATIENT, content=Block(type="document", source=Block(type="text", data=text)))


def error(kind: str, code: str) -> dict:
    return {"type": f"{kind}_tool_result_error", "error_code": code}


SEARCH_OK = [{"type": "web_search_result", "url": PATIENT}]


def test_calls_are_recorded_in_order_across_rounds() -> None:
    trace = build_trace([
        response(
            use("f1", "web_fetch", url=PATIENT),
            result("f1", "web_fetch_tool_result", error("web_fetch", "url_not_in_prior_context")),
        ),
        response(
            use("s1", "web_search", query="fhir patient"),
            result("s1", "web_search_tool_result", SEARCH_OK),
            use("f2", "web_fetch", url=PATIENT),
            result("f2", "web_fetch_tool_result", fetched("Patient.gender 0..1")),
        ),
    ])

    assert [(c["round"], c["tool"], c["result"]) for c in trace] == [
        (1, "fetch", "url_not_in_prior_context"),
        (2, "search", "ok"),
        (2, "fetch", "ok"),
    ]
    assert trace[0]["target"] == PATIENT
    assert trace[1]["target"] == "fhir patient"


def test_a_successful_fetch_keeps_the_page_text() -> None:
    trace = build_trace([response(use("f1", "web_fetch", url=PATIENT), result("f1", "web_fetch_tool_result", fetched("abc")))])

    assert (trace[0]["content"], trace[0]["content_chars"]) == ("abc", len("abc"))


def test_results_are_paired_by_id_not_position() -> None:
    trace = build_trace([response(
        use("f1", "web_fetch", url="https://hl7.org/a"),
        use("f2", "web_fetch", url="https://hl7.org/b"),
        result("f2", "web_fetch_tool_result", error("web_fetch", "url_not_allowed")),
        result("f1", "web_fetch_tool_result", fetched("page a")),
    )])

    assert [(c["target"], c["result"]) for c in trace] == [
        ("https://hl7.org/a", "ok"),
        ("https://hl7.org/b", "url_not_allowed"),
    ]


def test_a_result_can_arrive_in_a_later_round() -> None:
    """pause_turn can split a call from its result across responses."""
    trace = build_trace([
        response(use("f1", "web_fetch", url=PATIENT)),
        response(result("f1", "web_fetch_tool_result", fetched("late"))),
    ])

    assert trace[0]["round"] == 1
    assert trace[0]["result"] == "ok"
    assert trace[0]["content"] == "late"


def test_a_call_with_no_result_is_marked_missing() -> None:
    trace = build_trace([response(use("s1", "web_search", query="q"))])

    assert trace[0]["result"] == "missing"


def test_a_non_text_fetch_has_no_content() -> None:
    pdf = Block(type="web_fetch_result", url=PATIENT, content=Block(type="document", source=Block(type="base64", data="JVBERi0=")))
    trace = build_trace([response(use("f1", "web_fetch", url=PATIENT), result("f1", "web_fetch_tool_result", pdf))])

    assert trace[0]["result"] == "ok"
    assert trace[0]["content"] is None
    assert trace[0]["content_chars"] is None


def test_other_server_tools_keep_their_own_name() -> None:
    trace = build_trace([response(use("c1", "code_execution", code="print(1)"))])

    assert trace[0]["tool"] == "code_execution"


@pytest.mark.parametrize("code", ["url_not_allowed", "max_uses_exceeded", "url_not_accessible"])
def test_each_error_code_is_kept(code: str) -> None:
    trace = build_trace([response(use("f1", "web_fetch", url=PATIENT), result("f1", "web_fetch_tool_result", error("web_fetch", code)))])

    assert trace[0]["result"] == code
    assert "content" not in trace[0]


def test_dict_blocks_are_read_like_sdk_objects() -> None:
    trace = build_trace([{"content": [
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}},
        {"type": "web_search_tool_result", "tool_use_id": "s1", "content": SEARCH_OK},
    ]}])

    assert trace == [{"round": 1, "tool": "search", "target": "q", "result": "ok"}]


def test_count_filters_by_tool_and_result() -> None:
    trace = [
        {"round": 1, "tool": "fetch", "target": "a", "result": "url_not_in_prior_context"},
        {"round": 1, "tool": "search", "target": "q", "result": "ok"},
        {"round": 2, "tool": "fetch", "target": "a", "result": "ok"},
    ]

    assert [
        count(trace),
        count(trace, tool="fetch"),
        count(trace, result="ok"),
        count(trace, tool="fetch", result="ok"),
    ] == [3, 2, 2, 1]


def test_format_trace_lists_one_line_per_call() -> None:
    refused, read = format_trace([
        {"round": 1, "tool": "fetch", "target": PATIENT, "result": "url_not_in_prior_context"},
        {"round": 2, "tool": "fetch", "target": PATIENT, "result": "ok", "content": "x" * 10, "content_chars": 10},
    ]).splitlines()

    assert "url_not_in_prior_context" in refused
    assert PATIENT in read
    assert "10 chars" in read


def test_format_trace_says_when_there_were_no_calls() -> None:
    assert format_trace([]) == "(no web calls)"


def test_a_code_execution_result_is_paired_with_its_call() -> None:
    trace = build_trace([response(
        use("c1", "code_execution", code="print(page[:100])"),
        result("c1", "code_execution_tool_result", Block(type="code_execution_result", stdout="ok")),
    )])

    assert (trace[0]["tool"], trace[0]["result"]) == ("code_execution", "ok")


def test_other_code_execution_results_are_paired_too() -> None:
    trace = build_trace([response(
        use("b1", "bash_code_execution", command="ls"),
        result("b1", "bash_code_execution_tool_result", Block(type="bash_code_execution_result", stdout="")),
        use("t1", "text_editor_code_execution", command="view"),
        result("t1", "text_editor_code_execution_tool_result", Block(type="text_editor_code_execution_view_result")),
    )])

    assert [(c["tool"], c["result"]) for c in trace] == [
        ("bash_code_execution", "ok"),
        ("text_editor_code_execution", "ok"),
    ]
