"""Fetch long FHIR pages at several max_content_tokens and report where facts land.

Answers two questions before any experiment money is spent:
  1. Does a web_fetch_20260209 result surface as a web_fetch_tool_result block
     with the page text (what build_trace reads), or does dynamic filtering hide it?
  2. Which fact sits past the 10k truncation point but within reach at a larger size?

Run from the repo root:
    PYTHONUTF8=1 PYTHONPATH=services python -m poetry run python -m global_chat.tests.web_tools.calibrate
"""

# ruff: noqa: T201 - a command-line report, where printing is its output

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
load_dotenv()

from anthropic import Anthropic  # noqa: E402

from global_chat.config_loader import ConfigLoader  # noqa: E402
from models import resolve_model  # noqa: E402

from .trace import build_trace, format_trace  # noqa: E402

PAGES = {
    "https://hl7.org/fhir/R4/patient.html": [
        "male | female | other | unknown",
        "replaced-by",
        "seealso",
        "pat-1",
        "SHALL at least contain a contact's details or a reference to an organization",
        "death-date",
        "general-practitioner",
        "link",
    ],
    "https://hl7.org/fhir/R4/observation.html": [
        "registered | preliminary | final | amended",
        "obs-6",
        "obs-7",
        "code-value-concept",
        "combo-code-value-quantity",
        "component-value-concept",
    ],
}
SIZES = (10000, 25000, 50000)


def main() -> None:
    if os.getenv("ANTHROPIC_BASE_URL"):
        sys.exit("ANTHROPIC_BASE_URL is set, the web tools need a direct api.anthropic.com key")

    model = resolve_model(ConfigLoader().config["planner"]["model"])
    client = Anthropic()

    for page, facts in PAGES.items():
        for size in SIZES:
            tool = {
                "type": "web_fetch_20260209",
                "name": "web_fetch",
                "max_uses": 1,
                "max_content_tokens": size,
                "allowed_domains": ["hl7.org"],
            }
            response = client.beta.messages.create(
                model=model,
                max_tokens=2048,
                tools=[tool],
                messages=[{"role": "user", "content": f"Fetch {page} and then reply with just the word done"}],
            )
            print(f"\n=== {page} @ {size} tokens")
            print("block types:", [getattr(b, "type", None) for b in response.content])
            trace = build_trace([response])
            print(format_trace(trace))
            text = next((c["content"] for c in trace if c.get("content")), None)
            if text is None:
                print("NO FETCHED TEXT VISIBLE TO build_trace")
                continue
            lower = " ".join(text.lower().split())
            for fact in facts:
                at = lower.find(" ".join(fact.lower().split()))
                where = f"char {at} of {len(lower)}" if at >= 0 else "ABSENT"
                print(f"  {fact!r}: {where}")


if __name__ == "__main__":
    main()
