"""Unit tests for the dev-only mock LLM responder (APOLLO_MOCK_LLM)."""

import json
from pathlib import Path

import pytest
from global_chat import global_chat as entrypoint
from global_chat.mock_llm import _SCORE_THRESHOLD, build_mock_reply, pick_destination
from global_chat.router import RouterResult

_SAMPLE = Path(__file__).resolve().parents[4].parent / "lightning" / "priv" / "app_map.json"


@pytest.fixture(scope="module")
def app_map() -> list[dict]:
    """The real map Lightning sends, when the sibling checkout is present."""
    if not _SAMPLE.exists():
        pytest.skip("lightning checkout absent — real app_map.json fixture unavailable")
    return json.loads(_SAMPLE.read_text(encoding="utf-8"))


def test_github_question_lands_on_the_vcs_settings_tab(app_map: list[dict]) -> None:
    pick = pick_destination("How do I connect my project to GitHub for version control?", app_map)

    assert pick is not None
    page, tab, score = pick
    assert page["id"] == "project_settings"
    assert tab is not None
    assert tab["hash"] == "vcs"
    assert score >= _SCORE_THRESHOLD


def test_past_runs_question_lands_on_history(app_map: list[dict]) -> None:
    pick = pick_destination("see my past runs", app_map)

    assert pick is not None
    page, tab, _score = pick
    assert page["id"] == "project_history"
    assert tab is None


def test_password_question_lands_on_a_user_page_not_an_auth_one(app_map: list[dict]) -> None:
    pick = pick_destination("change my password", app_map)

    assert pick is not None
    page, _tab, _score = pick
    assert page["id"] == "profile"
    assert page["section"] == "user"


def test_api_tokens_question_lands_on_the_list_not_the_delete_dialog(app_map: list[dict]) -> None:
    """`api_token_delete` lives behind `/profile/tokens/:id/delete`, a path
    the tour planner cannot open, so it must never win the pick."""
    pick = pick_destination("where are my api tokens?", app_map)

    assert pick is not None
    page, tab, _score = pick
    assert page["id"] == "api_tokens"
    assert tab is None


def test_workflows_question_lands_on_the_workflows_page_not_a_settings_tab(app_map: list[dict]) -> None:
    """Label words are what users name: "workflows" must outweigh settings
    tabs whose descriptions merely mention the project."""
    pick = pick_destination("where can I see all workflows in this project?", app_map)

    assert pick is not None
    page, tab, _score = pick
    assert page["id"] == "project_workflows"
    assert tab is None


def test_collaborator_question_lands_on_the_collaboration_tab(app_map: list[dict]) -> None:
    pick = pick_destination("How do I add a collaborator to my project?", app_map)

    assert pick is not None
    page, tab, _score = pick
    assert page["id"] == "project_settings"
    assert tab is not None
    assert tab["hash"] == "collaboration"


def test_pages_with_unresolvable_path_params_are_never_candidates() -> None:
    """A perfect lexical match behind `:id` still loses to a weaker tourable
    page: a button the tour planner cannot follow is worse than none."""
    pages = [
        {"id": "thing_delete", "section": "user", "path": "/things/:id/delete",
         "label": "Delete thing", "description": "Delete a thing entry."},
        {"id": "things", "section": "user", "path": "/things",
         "label": "Things", "description": "List every thing entry."},
    ]

    pick = pick_destination("delete a thing entry", pages)

    assert pick is not None
    assert pick[0]["id"] == "things"
    # :project_id is the one parameter the tour planner can resolve.
    only_bad = [{"id": "thing_delete", "section": "user", "path": "/things/:id/delete",
                 "label": "Delete thing", "description": "Delete a thing entry."}]
    assert pick_destination("delete a thing entry", only_bad) is None


# Synthetic v2 fixture: the real priv/app_map.json may not carry elements yet.
ELEMENT_MAP = [
    {
        "id": "workflow_edit",
        "section": "project",
        "path": "/projects/:project_id/w/:id",
        "label": "Workflow editor",
        "description": "The collaborative canvas for building a workflow.",
        "elements": [
            {
                "id": "credential-picker",
                "label": "Credential picker",
                "description": "Choose which credential this step uses when it runs.",
                "hint": "Select a step to open its configuration panel first.",
            },
            {"id": "run-button", "label": "Run button", "description": "Run the workflow now."},
        ],
    },
    {
        "id": "credentials",
        "section": "user",
        "path": "/credentials",
        "label": "Credentials",
        "description": "List and manage the user's credentials for external services.",
    },
]


def test_on_page_question_picks_the_matching_element() -> None:
    pick = pick_destination("how do I set a credential on this step?", ELEMENT_MAP, page="workflows/wf/step")

    assert pick is not None
    page, target, _score = pick
    assert page["id"] == "workflow_edit"
    assert target is not None
    assert target["id"] == "credential-picker"
    assert "hash" not in target


def test_element_reply_carries_the_element_directive_label_and_hint() -> None:
    reply = build_mock_reply("how do I set a credential on this step?", ELEMENT_MAP, page="workflows/wf/step")

    body = reply.rsplit("```openfn-navigate\n", 1)[1].removesuffix("\n```")
    assert json.loads(body) == {"page": "workflow_edit", "element": "credential-picker"}
    assert "**Credential picker**" in reply
    assert "Select a step to open its configuration panel first." in reply


def test_elements_are_never_offered_without_a_page_hint() -> None:
    """Spotlighting a control on a page the user is not on is meaningless, and
    workflow_edit itself sits behind /w/:id, so with no hint there is nothing
    tourable left to offer."""
    assert pick_destination("how do I set a credential on this step?", ELEMENT_MAP) is None

    reply = build_mock_reply("how do I set a credential on this step?", ELEMENT_MAP)
    assert "openfn-navigate" not in reply


def test_elements_are_never_offered_from_a_different_page() -> None:
    """A page hint outside the workflow editor must not unlock its elements."""
    pick = pick_destination("how do I set a credential on this step?", ELEMENT_MAP, page="projects/p/history")

    assert pick is None


def test_maps_without_elements_behave_exactly_as_before(app_map: list[dict]) -> None:
    """The page hint is inert when no entry carries elements."""
    with_hint = pick_destination("see my past runs", app_map, page="workflows/wf/step")
    without_hint = pick_destination("see my past runs", app_map)

    assert with_hint == without_hint
    assert with_hint is not None
    assert with_hint[0]["id"] == "project_history"


def test_gibberish_matches_nothing(app_map: list[dict]) -> None:
    assert pick_destination("flibber jabberwock zzz glorp", app_map) is None


def test_stopwords_alone_match_nothing(app_map: list[dict]) -> None:
    assert pick_destination("how do I find the app?", app_map) is None


def test_admin_and_auth_pages_are_never_selected(app_map: list[dict]) -> None:
    """Feed every restricted page its own description — the strongest
    possible lure — and the pick must still stay in project/user."""
    for restricted in (p for p in app_map if p["section"] in ("admin", "auth")):
        pick = pick_destination(f"{restricted['label']} {restricted['description']}", app_map)

        if pick is not None:
            page, _tab, _score = pick
            assert page["section"] in ("project", "user"), restricted["id"]


def test_missing_or_empty_map_matches_nothing() -> None:
    assert pick_destination("see my past runs", None) is None
    assert pick_destination("see my past runs", []) is None


def test_ties_break_deterministically() -> None:
    pages = [
        {"id": "b_page", "section": "project", "label": "Zebra care", "description": ""},
        {"id": "a_page", "section": "project", "label": "Zebra care", "description": ""},
    ]

    pick = pick_destination("zebra care", pages)

    assert pick is not None
    assert pick[0]["id"] == "a_page"


def test_reply_ends_with_a_parseable_navigate_fence(app_map: list[dict]) -> None:
    reply = build_mock_reply("How do I connect my project to GitHub for version control?", app_map)

    prose, fence = reply.rsplit("\n\n", 1)
    assert "**Settings**" in prose
    assert fence.startswith("```openfn-navigate\n")
    assert fence.endswith("\n```")
    directive = json.loads(fence.removeprefix("```openfn-navigate\n").removesuffix("\n```"))
    assert directive == {"page": "project_settings", "tab": "vcs"}


def test_reply_without_a_tab_omits_the_tab_key(app_map: list[dict]) -> None:
    reply = build_mock_reply("see my past runs", app_map)

    body = reply.rsplit("```openfn-navigate\n", 1)[1].removesuffix("\n```")
    assert json.loads(body) == {"page": "project_history"}


def test_no_match_reply_has_no_fence(app_map: list[dict]) -> None:
    reply = build_mock_reply("flibber jabberwock zzz", app_map)

    assert "couldn't find a matching page" in reply
    assert "mock mode" in reply
    assert "openfn-navigate" not in reply


def test_main_short_circuits_before_the_router(app_map: list[dict], monkeypatch: pytest.MonkeyPatch) -> None:
    """With the env var set, main() must answer without constructing the
    router (which would demand an Anthropic key and make API calls)."""
    monkeypatch.setenv("APOLLO_MOCK_LLM", "1")

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("RouterAgent must not be constructed in mock mode")

    monkeypatch.setattr(entrypoint, "RouterAgent", explode)

    result = entrypoint.main({
        "content": "where can I see my past runs?",
        "app_map": app_map,
        "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    })

    assert "```openfn-navigate" in result["response"]
    assert result["response_segments"] == [{"type": "text", "content": result["response"]}]
    assert result["attachments"] == []
    # History grows by this turn, on top of what was sent.
    assert [t["role"] for t in result["history"]] == ["user", "assistant", "user", "assistant"]
    assert result["history"][-1]["content"] == result["response"]
    assert result["usage"]["input_tokens"] == 0
    assert result["meta"]["mock_llm"] is True
    assert result["meta"]["agents"] == ["mock_llm"]


def test_mock_mode_streams_through_the_real_event_mechanism(
    app_map: list[dict], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """options.stream=true must produce the same EVENT: lines a planner reply
    does — message_start, several text deltas, message_stop."""
    monkeypatch.setenv("APOLLO_MOCK_LLM", "true")

    result = entrypoint.main({
        "content": "see my past runs",
        "app_map": app_map,
        "options": {"stream": True},
    })

    events = [line for line in capsys.readouterr().out.splitlines() if line.startswith("EVENT:")]
    min_deltas = 2  # "a few chunked text deltas", not one monolithic block
    kinds = [line.split(":", 2)[1] for line in events]
    assert kinds[0] == "message_start"
    assert kinds.count("content_block_delta") >= min_deltas
    assert kinds[-1] == "message_stop"
    # The streamed deltas reassemble into exactly the returned response.
    deltas = [json.loads(line.split(":", 2)[2]) for line in events if "content_block_delta" in line.split(":", 2)[1]]
    assert "".join(d["delta"]["text"] for d in deltas) == result["response"]


def test_mock_mode_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset (or any non-truthy value) must fall through to the normal path."""
    monkeypatch.delenv("APOLLO_MOCK_LLM", raising=False)
    sentinel = {"response": "real path", "response_segments": [], "attachments": [],
                "history": [], "usage": {}, "meta": {}}

    class FakeRouter:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def route_and_execute(self, **_kwargs: object) -> RouterResult:
            return RouterResult(**sentinel)

    monkeypatch.setattr(entrypoint, "RouterAgent", FakeRouter)
    monkeypatch.setattr(entrypoint, "ConfigLoader", lambda *_a, **_k: None)

    result = entrypoint.main({"content": "hi"})

    assert result["response"] == "real path"
