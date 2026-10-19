"""The experiment's variants and stages. A variant name composes parts with '+'."""

import re
from dataclasses import dataclass, field

SEARCH_FIRST = (
    "- `web_fetch` can only open a URL that already appears in this conversation: in the "
    "user's message, or in an earlier search or fetch result. URLs you remember, and URLs in "
    "these instructions, are refused. Search first, then fetch a URL from the results."
)

FINDINGS = (
    "- Fetched pages are not kept after this turn. When you used them, state the specific "
    "facts you relied on and name the page, so a follow-up question can build on your "
    "answer without fetching again."
)

EXAMPLE_URL = " (e.g. `https://hl7.org/fhir/R4/patient.html`)"

# One entry page per allowed domain in config.yaml.
ENTRY_URLS = ("https://hl7.org/fhir/R4/", "https://docs.openfn.org/")

INJECT_TEMPLATE = "(Pages you can open with web_fetch: {urls})"


@dataclass
class Variant:
    name: str
    web_search: dict = field(default_factory=dict)
    prompt_suffix: str = ""
    # Text removed from the web prompt before the suffix is appended.
    prompt_removals: tuple[str, ...] = ()
    inject_urls: tuple[str, ...] = ()
    # 0 = no change, 1 = prompt or config change, 2 = production code change.
    complexity: int = 0


PARTS = {
    "base": Variant("base"),
    "1a": Variant("1a", prompt_suffix=SEARCH_FIRST, complexity=1),
    "1b": Variant("1b", inject_urls=ENTRY_URLS, complexity=2),
    "1c": Variant("1c", prompt_suffix=SEARCH_FIRST, inject_urls=ENTRY_URLS, complexity=2),
    "1d": Variant("1d", prompt_suffix=SEARCH_FIRST, prompt_removals=(EXAMPLE_URL,), complexity=1),
    "findings": Variant("findings", prompt_suffix=FINDINGS, complexity=1),
}

STAGES = {
    0: {"variants": [], "scenarios": [
        "control_openfn_concept", "control_code_edit", "fhir_shallow",
        "fhir_deep", "off_allowlist", "multi_turn",
    ]},
    1: {"variants": ["1a", "1b", "1c"], "scenarios": [
        "control_openfn_concept", "control_code_edit", "fhir_shallow", "fhir_deep",
    ]},
    2: {"variants": ["25k", "50k"], "scenarios": ["fhir_shallow", "fhir_deep"]},
    3: {"variants": ["findings"], "scenarios": ["multi_turn"]},
}


def resolve_variant(name: str) -> Variant:
    """Compose 'base+1c+25k' into one Variant; later parts win on conflicting config keys."""
    web_search: dict = {}
    suffixes: list[str] = []
    removals: list[str] = []
    inject: tuple[str, ...] = ()
    complexity = 0
    for part in (parse_part(p) for p in name.split("+")):
        web_search.update(part.web_search)
        if part.prompt_suffix and part.prompt_suffix not in suffixes:
            suffixes.append(part.prompt_suffix)
        removals.extend(r for r in part.prompt_removals if r not in removals)
        inject = inject or part.inject_urls
        complexity = max(complexity, part.complexity)
    return Variant(
        name,
        web_search=web_search,
        prompt_suffix="\n".join(suffixes),
        prompt_removals=tuple(removals),
        inject_urls=inject,
        complexity=complexity,
    )


def parse_part(name: str) -> Variant:
    size = re.fullmatch(r"(\d+)k", name)
    if size:
        return Variant(name, web_search={"max_content_tokens": int(size.group(1)) * 1000}, complexity=1)
    return PARTS[name]
