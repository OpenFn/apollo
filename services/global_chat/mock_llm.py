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


def pick_destination(content: str, app_map: list[dict] | None) -> tuple[dict, dict | None, int] | None:
    """The best (page, tab, score) for the user's sentence, or None.

    Pure lexical overlap: page candidates score the content tokens shared
    with label+description, counting label hits again at _LABEL_WEIGHT; a
    (page, tab) candidate adds the tab's own overlap twice, so tab-specific
    words outrank the page they sit on. Pages whose path the tour planner
    cannot open (see _tourable) are never candidates. Deterministic: ties
    break on alphabetical page id, bare page before its tabs, then tab hash.
    """
    if not app_map:
        return None

    asked = _tokens(content)
    if not asked:
        return None

    candidates = []  # (-score, page_id, tab_rank, tab_hash, page, tab)
    for page in app_map:
        if not isinstance(page, dict) or page.get("section") not in _ALLOWED_SECTIONS:
            continue
        if not _tourable(page.get("path")):
            continue
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id:
            continue

        base = len(asked & _page_tokens(page)) + _LABEL_WEIGHT * len(asked & _tokens(page.get("label")))
        candidates.append((-base, page_id, 0, "", page, None))

        tabs = page.get("tabs")
        for tab in tabs if isinstance(tabs, list) else []:
            if not isinstance(tab, dict) or not isinstance(tab.get("hash"), str) or not tab["hash"]:
                continue
            score = base + 2 * len(asked & _tab_tokens(tab))
            candidates.append((-score, page_id, 1, tab["hash"], page, tab))

    if not candidates:
        return None

    best = min(candidates)
    score = -best[0]
    if score < _SCORE_THRESHOLD:
        return None
    return (best[4], best[5], score)


def build_mock_reply(content: str, app_map: list[dict] | None) -> str:
    """Templated prose plus the `openfn-navigate` fence, or a no-match line.

    The fence is byte-for-byte the directive shape the real planner is
    prompted to emit, because the point of mock mode is exercising the
    client's handling of it.
    """
    pick = pick_destination(content, app_map)
    if pick is None:
        return _NO_MATCH_REPLY

    page, tab, _score = pick
    label = page.get("label") or page.get("id")

    first = f"You can do that on the **{label}** page"
    if tab is not None:
        first += f", under the **{tab.get('label') or tab['hash']}** tab"
    first += "."

    description = (tab.get("description") if tab else None) or page.get("description") or ""
    where = f"`{page['path']}`" if page.get("path") else f"the {label} page"
    if tab is not None:
        where += f" (tab `#{tab['hash']}`)"
    last = f"You'll find it at {where}."

    directive = {"page": page["id"]}
    if tab is not None:
        directive["tab"] = tab["hash"]
    fence = f"```openfn-navigate\n{json.dumps(directive)}\n```"

    prose = " ".join(part for part in (first, description, last) if part)
    return f"{prose}\n\n{fence}"


def run_mock(payload: "Payload") -> dict:
    """Serve one turn without any model: same stream events, same result shape.

    The reply flows through the StreamManager exactly as a planner reply does
    (message_start, a few text deltas, completion), so Lightning's channel/SSE
    handling is exercised, and the returned dict mirrors what main() returns
    on the real path — with zeroed usage and a meta flag naming the mock.
    """
    logger.info("MOCK LLM mode active (APOLLO_MOCK_LLM) — no Anthropic call made")

    reply = build_mock_reply(payload.content, payload.app_map)

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
