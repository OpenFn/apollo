"""Unit tests for the planner's web tool definitions."""

from global_chat.tools.tool_definitions import build_web_tools

MAX_USES = 5
MAX_CONTENT_TOKENS = 10000
ALLOWED_DOMAINS = ["docs.dhis2.org", "docs.openfn.org"]

WEB_CONFIG = {
    "planner": {
        "web_search": {
            "max_uses": MAX_USES,
            "max_content_tokens": MAX_CONTENT_TOKENS,
            "allowed_domains": ALLOWED_DOMAINS,
        },
    },
}


def by_name(tools: list[dict]) -> dict[str, dict]:
    return {tool["name"]: tool for tool in tools}


def test_no_web_search_block_leaves_the_tools_off() -> None:
    assert build_web_tools({"planner": {}}) == []
    assert build_web_tools({}) == []


def test_empty_allowlist_leaves_the_tools_off() -> None:
    """The empty allowlist is the server-side kill switch, not open-web."""
    assert build_web_tools({"planner": {"web_search": {"allowed_domains": []}}}) == []
    assert build_web_tools({"planner": {"web_search": {"max_uses": 5}}}) == []


def test_populated_allowlist_builds_both_tools_with_the_current_type_strings() -> None:
    tools = by_name(build_web_tools(WEB_CONFIG))

    assert tools["web_search"]["type"] == "web_search_20260209"
    assert tools["web_fetch"]["type"] == "web_fetch_20260209"


def test_max_content_tokens_reaches_the_fetch_tool_only() -> None:
    """Sending max_content_tokens on web_search is a 400 — it must not be set."""
    tools = by_name(build_web_tools(WEB_CONFIG))

    assert "max_content_tokens" not in tools["web_search"]
    assert tools["web_fetch"]["max_content_tokens"] == MAX_CONTENT_TOKENS


def test_allowlist_and_max_uses_go_on_both_tools() -> None:
    tools = by_name(build_web_tools(WEB_CONFIG))

    for tool in tools.values():
        assert tool["max_uses"] == MAX_USES
        assert tool["allowed_domains"] == ALLOWED_DOMAINS
        assert "blocked_domains" not in tool


def test_the_configured_allowlist_is_copied_not_aliased() -> None:
    """A caller mutating the returned list must not edit config in place."""
    config = {"planner": {"web_search": {"allowed_domains": ["docs.dhis2.org"]}}}

    build_web_tools(config)[0]["allowed_domains"].append("evil.example")

    assert config["planner"]["web_search"]["allowed_domains"] == ["docs.dhis2.org"]
