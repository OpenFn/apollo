"""Unit tests for rendering the Lightning app map into prompt markdown."""

import json
from pathlib import Path

from global_chat.app_map import format_app_map

APP_MAP = [
    {
        "id": "project_history",
        "path": "/projects/:project_id/history",
        "module": "LightningWeb.RunLive.Index",
        "label": "History",
        "section": "project",
        "description": "Search and filter past work orders and runs.",
        "tabs": [
            {"hash": "vcs", "label": "Version Control", "description": "Connect GitHub."},
        ],
    },
    {
        "id": "admin_users",
        "path": "/settings/users",
        "label": "Users",
        "section": "admin",
        "description": "Superuser list of every user account.",
    },
    {
        "id": "profile",
        "path": "/profile",
        "label": "User profile",
        "section": "user",
        "description": "Edit your own account.",
    },
]


def test_pages_are_grouped_by_section_in_canonical_order() -> None:
    rendered = format_app_map(APP_MAP)

    # project, then user, then admin — not the input order, not alphabetical.
    assert rendered.index("### Project") < rendered.index("### User") < rendered.index("### Admin")


def test_a_page_renders_label_id_path_and_description_on_one_line() -> None:
    rendered = format_app_map(APP_MAP)

    assert (
        "- **History** [id: project_history] (`/projects/:project_id/history`): "
        "Search and filter past work orders and runs." in rendered
    )


def test_every_page_with_an_id_carries_it_on_its_line() -> None:
    """The id is the handle the navigation directive points at, so a page
    rendered without it is a page the "Take me there" button can never reach."""
    rendered = format_app_map(APP_MAP)

    for entry in APP_MAP:
        assert f"[id: {entry['id']}]" in rendered


def test_tabs_render_as_indented_sub_bullets() -> None:
    rendered = format_app_map(APP_MAP)

    assert "\n  - Version Control (#vcs): Connect GitHub.\n" in rendered + "\n"


def test_pages_within_a_section_sort_by_label() -> None:
    pages = [
        {"label": "Zulu", "path": "/z", "section": "project"},
        {"label": "Alpha", "path": "/a", "section": "project"},
    ]

    rendered = format_app_map(pages)

    assert rendered.index("Alpha") < rendered.index("Zulu")


def test_unknown_sections_render_after_the_canonical_ones() -> None:
    pages = [
        {"label": "New thing", "path": "/n", "section": "experimental"},
        {"label": "Login", "path": "/users/log_in", "section": "auth"},
    ]

    rendered = format_app_map(pages)

    assert rendered.index("### Auth") < rendered.index("### Experimental")


def test_malformed_entries_are_skipped_without_crashing() -> None:
    pages = [
        "not a dict",
        {"section": "project"},  # nothing to name it by
        {"label": "Real page", "path": "/real", "section": "project", "tabs": "not a list"},
        {"label": "Tabbed", "path": "/t", "section": "project", "tabs": ["not a dict", {"hash": "", "label": ""}]},
    ]

    rendered = format_app_map(pages)

    assert "- **Real page** (`/real`)" in rendered
    assert "- **Tabbed** (`/t`)" in rendered
    assert "not a dict" not in rendered


def test_an_entry_without_a_label_falls_back_to_its_id() -> None:
    rendered = format_app_map([{"id": "mystery_page", "path": "/m", "section": "project"}])

    assert "- **mystery_page** [id: mystery_page] (`/m`)" in rendered


def test_an_entry_without_an_id_renders_no_id_bracket() -> None:
    rendered = format_app_map([{"label": "No handle", "path": "/n", "section": "project"}])

    assert "- **No handle** (`/n`)" in rendered
    assert "[id:" not in rendered


def test_missing_optional_keys_render_what_exists() -> None:
    rendered = format_app_map([{"label": "Bare", "section": "user"}])

    assert "- **Bare**" in rendered
    assert "(`" not in rendered  # no path, so no path parens


def test_empty_and_none_maps_render_to_nothing() -> None:
    assert format_app_map(None) == ""
    assert format_app_map([]) == ""


def test_rendering_is_deterministic() -> None:
    assert format_app_map(APP_MAP) == format_app_map(list(reversed(APP_MAP)))


def test_the_real_lightning_app_map_renders_every_page() -> None:
    """The sample Lightning actually sends, when present next to the repo.

    Skipped silently when the sibling checkout is absent so CI stays green.
    """
    sample = Path(__file__).resolve().parents[4].parent / "lightning" / "priv" / "app_map.json"
    if not sample.exists():
        return

    pages = json.loads(sample.read_text(encoding="utf-8"))
    rendered = format_app_map(pages)

    assert rendered.count("- **") == len(pages)  # one page bullet per entry
    for section in {p["section"] for p in pages}:
        assert f"### {section.capitalize()}" in rendered
    # Every page is addressable by the navigation directive.
    for page in pages:
        assert f"[id: {page['id']}]" in rendered
