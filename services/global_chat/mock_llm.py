"""Dev-only mock responder for global_chat (APOLLO_MOCK_LLM=1).

Answers where-is questions from the Lightning app map with simple lexical
matching and emits the same `openfn-navigate` directive the real planner is
prompted to produce, so the full Lightning -> Apollo -> chat UI -> "Take me
there" flow can be exercised without an Anthropic key. Never active unless
the environment variable is set; makes no network calls of any kind.
"""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.append(str(Path(__file__).parent.parent))

from streaming_util import StreamManager
from util import APOLLO_VERSION, create_logger

if TYPE_CHECKING:
    from global_chat.global_chat import Payload

logger = create_logger(__name__)

# Same restriction the real prompt states: the button must only point at
# pages a regular user can reach.
_ALLOWED_SECTIONS = ("project", "user")

# A match needs at least this much overlap; below it, admitting no match
# beats pointing the button somewhere wrong.
_SCORE_THRESHOLD = 2

# Words saying how a question is asked, not what it is about. Domain words
# (runs, credentials, password...) deliberately stay out.
_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "were", "will", "would", "should",
    "could", "can", "you", "your", "our", "has", "have", "had", "how",
    "where", "what", "when", "who", "why", "which", "this", "that", "these",
    "those", "there", "here", "with", "without", "into", "from", "about",
    "does", "did", "don", "doesn", "not", "any", "all", "get", "got", "see",
    "want", "need", "like", "please", "show", "find", "tell", "take",
    "lightning", "app", "openfn",
})

_NO_MATCH_REPLY = (
    "I couldn't find a matching page for that (mock mode). "
    "Try naming what you want to do in the Lightning app."
)


_MIN_TOKEN_LEN = 3


def _tokens(text: object) -> set[str]:
    """Lowercased alphanumeric words worth matching on."""
    if not isinstance(text, str):
        return set()
    words = "".join(c if c.isalnum() else " " for c in text.lower()).split()
    return {w for w in words if len(w) >= _MIN_TOKEN_LEN and w not in _STOPWORDS}


def _page_tokens(page: dict) -> set[str]:
    return _tokens(page.get("label")) | _tokens(page.get("description"))


# Label words ("Workflows", "History", "API Tokens") are what users name, so
# a label hit counts this much on top of the shared label+description overlap.
_LABEL_WEIGHT = 3


def _tourable(path: object) -> bool:
    """Whether Lightning's tour planner can actually open this path.

    It can only resolve `:project_id`; any other `:param` segment (`:id`,
    `:token`, ...) would make a dead "Take me there" button, so pages behind
    one are never candidates. A missing path disqualifies nothing.
    """
    if not isinstance(path, str):
        return True
    return all(
        not segment.startswith(":") or segment == ":project_id"
        for segment in path.split("/")
    )


def _tab_tokens(tab: dict) -> set[str]:
    return _tokens(tab.get("label")) | _tokens(tab.get("description"))


def _element_tokens(element: dict) -> set[str]:
    return _tokens(element.get("label")) | _tokens(element.get("description"))


# How an element's own word overlap counts — same footing as a tab's.
_ELEMENT_WEIGHT = 2


def _element_candidates(entry: dict, page_id: str, asked: set[str]) -> list[tuple]:
    """Candidate tuples for the in-page controls of the page the user is on.

    Exempt from the tourable gate: spotlighting navigates nowhere. Rank 2
    places elements after the bare page and its tabs on tied scores.
    """
    elements = entry.get("elements")
    candidates = []
    for element in elements if isinstance(elements, list) else []:
        if not isinstance(element, dict) or not isinstance(element.get("id"), str) or not element["id"]:
            continue
        score = _ELEMENT_WEIGHT * len(asked & _element_tokens(element))
        candidates.append((-score, page_id, 2, element["id"], entry, element))
    return candidates


def _current_page_id(page_hint: object) -> str | None:
    """Which map page the payload's `page` value says the user is on.

    v2 recognises one shape: any `workflows/...` page URL means the user is
    in the workflow editor. Element spotlights only make sense on the page
    the user is already on, so an unrecognised hint offers no elements.
    """
    if isinstance(page_hint, str) and page_hint.startswith("workflows/"):
        return "workflow_edit"
    return None


def pick_destination(
    content: str, app_map: list[dict] | None, page: str | None = None,
) -> tuple[dict, dict | None, int] | None:
    """The best (page, target, score) for the user's sentence, or None.

    `target` is None for a bare page, a tab dict (carries "hash"), or an
    element dict (carries "id" and no "hash") when the user's current page
    (the `page` hint) has an in-page control matching their words.

    Pure lexical overlap: page candidates score the content tokens shared
    with label+description, counting label hits again at _LABEL_WEIGHT; a
    (page, tab) candidate adds the tab's own overlap twice, so tab-specific
    words outrank the page they sit on. Pages whose path the tour planner
    cannot open (see _tourable) are never navigation candidates — but their
    elements still are when the user is already on them, because an element
    spotlight navigates nowhere. Deterministic: ties break on alphabetical
    page id, bare page before tabs before elements, then target id.
    """
    if not app_map:
        return None

    asked = _tokens(content)
    if not asked:
        return None

    on_page_id = _current_page_id(page)

    candidates = []  # (-score, page_id, target_rank, target_id, page, target)
    for entry in app_map:
        if not isinstance(entry, dict) or entry.get("section") not in _ALLOWED_SECTIONS:
            continue
        page_id = entry.get("id")
        if not isinstance(page_id, str) or not page_id:
            continue

        # Elements are offered only for the page the user is on.
        if page_id == on_page_id:
            candidates.extend(_element_candidates(entry, page_id, asked))

        if not _tourable(entry.get("path")):
            continue

        base = len(asked & _page_tokens(entry)) + _LABEL_WEIGHT * len(asked & _tokens(entry.get("label")))
        candidates.append((-base, page_id, 0, "", entry, None))

        tabs = entry.get("tabs")
        for tab in tabs if isinstance(tabs, list) else []:
            if not isinstance(tab, dict) or not isinstance(tab.get("hash"), str) or not tab["hash"]:
                continue
            score = base + 2 * len(asked & _tab_tokens(tab))
            candidates.append((-score, page_id, 1, tab["hash"], entry, tab))

    if not candidates:
        return None

    best = min(candidates)
    score = -best[0]
    if score < _SCORE_THRESHOLD:
        return None
    return (best[4], best[5], score)


def _fence(directive: dict) -> str:
    return f"```openfn-navigate\n{json.dumps(directive)}\n```"


def _element_reply(page: dict, element: dict) -> str:
    """Prose plus an element-spotlight fence for a control on the current page."""
    page_label = page.get("label") or page.get("id")
    el_label = element.get("label") or element["id"]

    parts = [f"You can do that right here on the **{page_label}** page, using the **{el_label}** control."]
    if element.get("description"):
        parts.append(element["description"])
    if element.get("hint"):
        parts.append(f"Hint: {element['hint']}")

    directive = {"page": page["id"], "element": element["id"]}
    return f"{' '.join(parts)}\n\n{_fence(directive)}"


def build_mock_reply(content: str, app_map: list[dict] | None, page: str | None = None) -> str:
    """Templated prose plus the `openfn-navigate` fence, or a no-match line.

    The fence is byte-for-byte a directive shape the real planner is
    prompted to emit — navigation ({"page", "tab"?}) or element spotlight
    ({"page", "element"}) — because the point of mock mode is exercising the
    client's handling of them.
    """
    pick = pick_destination(content, app_map, page)
    if pick is None:
        return _NO_MATCH_REPLY

    target_page, target, _score = pick
    if target is not None and "hash" not in target:
        return _element_reply(target_page, target)

    tab = target
    label = target_page.get("label") or target_page.get("id")

    first = f"You can do that on the **{label}** page"
    if tab is not None:
        first += f", under the **{tab.get('label') or tab['hash']}** tab"
    first += "."

    description = (tab.get("description") if tab else None) or target_page.get("description") or ""
    where = f"`{target_page['path']}`" if target_page.get("path") else f"the {label} page"
    if tab is not None:
        where += f" (tab `#{tab['hash']}`)"
    last = f"You'll find it at {where}."

    directive = {"page": target_page["id"]}
    if tab is not None:
        directive["tab"] = tab["hash"]

    prose = " ".join(part for part in (first, description, last) if part)
    return f"{prose}\n\n{_fence(directive)}"


def run_mock(payload: "Payload") -> dict:
    """Serve one turn without any model: same stream events, same result shape.

    The reply flows through the StreamManager exactly as a planner reply does
    (message_start, a few text deltas, completion), so Lightning's channel/SSE
    handling is exercised, and the returned dict mirrors what main() returns
    on the real path — with zeroed usage and a meta flag naming the mock.
    """
    logger.info("MOCK LLM mode active (APOLLO_MOCK_LLM) — no Anthropic call made")

    reply = build_mock_reply(payload.content, payload.app_map, payload.page)

    manager = StreamManager(model="mock-llm", stream=payload.get_stream())
    # A few deltas rather than one, so the client's incremental rendering
    # runs, not just its final-message path.
    step = max(1, len(reply) // 3)
    for start in range(0, len(reply), step):
        manager.send_text(reply[start:start + step])
    manager.end_stream()

    history = list(payload.history or [])
    history.append({"role": "user", "content": payload.content})
    history.append({"role": "assistant", "content": reply})

    return {
        "response": reply,
        "response_segments": [{"type": "text", "content": reply}],
        "attachments": [],
        "history": history,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "meta": {
            "agents": ["mock_llm"],
            "mock_llm": True,
            "apollo_version": APOLLO_VERSION,
        },
    }
