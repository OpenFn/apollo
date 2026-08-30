"""Emit the edge codepoints of every range table in `services/name_rules.py`.

`probe.exs` used to sweep a hand-picked slice of each Hangul range — a few
syllables, `0x1161..0x1165` of the vowels — and the last three rounds of this
review each found the same thing: a boundary the slice never touched. U+1160
HANGUL JUNGSEONG FILLER is assigned and GCB=V, and narrowing `_HANGUL_V` to
start at U+1161 left the harness at exit 0.

So the probe reads this file rather than naming codepoints itself. Every range
in the tables contributes its first and last member and one either side, which
is where an off-by-one lives. Add a range to `name_rules` and it is swept
automatically; that is the point.

Run before `probe.exs`:

    python3 edges.py && elixir probe.exs && python3 check.py
"""

# A developer CLI: printing is its output, and it is all about raw codepoint
# values.
# ruff: noqa: T201, PLR2004

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

import name_rules as nr

OUT = Path(__file__).parent / "out"

#: Every range-shaped table. `_LAG_*` and `_EXT_PICT_RANGES` are tuples of
#: (low, high) pairs; the Hangul ones are tuples of `range` objects.
RANGE_TABLES = {
    "_HANGUL_L": nr._HANGUL_L,
    "_HANGUL_V": nr._HANGUL_V,
    "_HANGUL_T": nr._HANGUL_T,
    "_HANGUL_SYLLABLES": (nr._HANGUL_SYLLABLES,),
    "_REGIONAL_INDICATOR": (nr._REGIONAL_INDICATOR,),
    "_TAGS": (nr._TAGS,),
    "_SKIN_TONES": (nr._SKIN_TONES,),
    "_C0": (nr._C0,),
    "_C1": (nr._C1,),
    "_SURROGATES": (nr._SURROGATES,),
    "_LAG_EXTEND": nr._LAG_EXTEND,
    "_LAG_CONTROL": nr._LAG_CONTROL,
    "_EXT_PICT_RANGES": nr._EXT_PICT_RANGES,
}


def _bounds(entry: object) -> tuple[int, int]:
    if isinstance(entry, range):
        return entry.start, entry.stop - 1
    low, high = entry
    return low, high


def main() -> int:
    edges: set[int] = set()
    for table in RANGE_TABLES.values():
        for entry in table:
            low, high = _bounds(entry)
            # The boundary and one step outside it, both ends. Inside-the-range
            # values are already covered by the sweeps; it is the step across
            # the edge that a hand-picked slice never makes.
            edges.update({low - 1, low, high, high + 1})

    edges = {code for code in edges if 0 <= code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF}

    OUT.mkdir(exist_ok=True)
    (OUT / "range_edges.txt").write_text(
        "\n".join(f"{code:X}" for code in sorted(edges)) + "\n",
    )
    print(f"wrote out/range_edges.txt: {len(edges)} edge codepoints "
          f"from {sum(len(t) for t in RANGE_TABLES.values())} ranges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
