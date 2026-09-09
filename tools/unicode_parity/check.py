"""Compare services/name_rules.py against the Elixir ground truth.

Run `elixir probe.exs` first (see its header). This script does two things:

  * reports every disagreement between Apollo's clustering and Elixir's, in
    both the per-codepoint classification and the derived tables;
  * prints the table literals to paste back into `name_rules` when a Unicode
    version has moved.

Exit status is non-zero if anything disagrees, so it can be wired into CI on a
runner that has Elixir.

Usage, from this directory:

    elixir probe.exs
    python3 check.py            # report
    python3 check.py --tables   # also print the table literals
"""

# This is a developer CLI: printing is its output, and it is all about raw
# codepoint values, so the "magic value" and "no print" rules do not apply.
# ruff: noqa: T201, PLR2004

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

import name_rules as nr

OUT = Path(__file__).parent / "out"


def _codepoints(path: Path) -> set[int]:
    return {int(line.split()[0], 16) for line in path.read_text().split("\n") if line.strip()}


def _ranges(codes: set[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for code in sorted(codes):
        if out and code == out[-1][1] + 1:
            out[-1][1] = code
        else:
            out.append([code, code])
    return [(a, b) for a, b in out]


def _literal(name: str, ranges: list[tuple[int, int]], per_line: int = 3) -> str:
    rows = [
        "    " + " ".join(f"(0x{a:04X}, 0x{b:04X})," for a, b in ranges[i : i + per_line])
        for i in range(0, len(ranges), per_line)
    ]
    return f"{name} = (\n" + "\n".join(rows) + "\n)\n"


def check_classes() -> tuple[int, dict[str, list[int]]]:
    """Every codepoint must land in the same break-class bucket as Elixir."""
    elixir: dict[int, str] = {}
    for line in (OUT / "classmap.txt").read_text().split("\n"):
        if line.strip():
            code, bucket = line.split()
            elixir[int(code, 16)] = bucket

    buckets = {nr._EXTEND: "A", nr._SPACING: "A", nr._PREP: "P", nr._CONTROL: "C", nr._JOIN: "J"}
    wrong: dict[str, list[int]] = {"A": [], "P": [], "C": [], "O": []}

    for code in range(0x110000):
        if 0xD800 <= code <= 0xDFFF:
            continue
        mine = buckets.get(nr._break_class(chr(code)), "O")
        if mine == "J":
            continue
        theirs = elixir.get(code, "O")
        if mine != theirs:
            wrong[theirs].append(code)

    return sum(len(v) for v in wrong.values()), wrong


def check_extpict() -> set[int]:
    """Extended_Pictographic is not a break class, so it needs its own check.

    This is the one the codepoint sweep structurally cannot make. An over-broad
    set here silently changes GB11 and nothing else notices.
    """
    theirs = _codepoints(OUT / "extpict.txt")
    mine = {c for c in range(0x110000) if not (0xD800 <= c <= 0xDFFF) and nr._is_ext_pict(c)}
    return mine ^ theirs


def check_trim() -> set[str]:
    theirs = {chr(c) for c in _codepoints(OUT / "trim.txt")}
    return theirs ^ set(nr._TRIM_CHARS)


def check_lookback() -> set[int]:
    """What a GB11 emoji run may be separated from its ZWJ by."""
    theirs = _codepoints(OUT / "lookback.txt")
    mine = {
        c
        for c in range(0x110000)
        if not (0xD800 <= c <= 0xDFFF) and nr._break_class(chr(c)) in nr._RUN_CONTINUES
    }
    return mine ^ theirs


def check_clusters() -> tuple[int, int, list]:
    """Cluster boundaries against Elixir, not just cluster counts.

    Nothing else here can see the clusterer's rules: the per-codepoint sweep
    buckets Hangul and regional indicators to "other", so the GB12/GB13 parity
    rule and the CR-LF rule were untested by every check in this file.
    """
    path = OUT / "clusters.txt"
    mismatches = []
    total = 0
    for line in path.read_text().split("\n"):
        if not line.strip():
            continue
        total += 1
        raw, expected = line.split("\t")
        text = "".join(chr(int(c, 16)) for c in raw.split(","))
        want = [
            "".join(chr(int(c, 16)) for c in group.split("+"))
            for group in expected.split(",")
        ]
        got = nr.grapheme_clusters(text)
        if got != want:
            mismatches.append((text, want, got))
    return len(mismatches), total, mismatches


#: Everything probe.exs writes. Checked up front so a partial or stale run is
#: an error rather than a quiet subset.
EXPECTED_OUTPUTS = (
    "classmap.txt", "extpict.txt", "trim.txt", "lookback.txt",
    "clusters.txt", "range_edges.txt", "version.txt",
)


def main() -> int:
    if not OUT.exists():
        print(f"No probe output at {OUT}. Run `elixir probe.exs` first.")
        return 2

    missing = [name for name in EXPECTED_OUTPUTS if not (OUT / name).exists()]
    if missing:
        print(f"Probe output incomplete: {', '.join(missing)}. Re-run `elixir probe.exs`.")
        return 2

    stale = [p.name for p in OUT.iterdir() if p.is_file() and p.name not in EXPECTED_OUTPUTS]
    if stale:
        print(f"Stale files in {OUT}: {', '.join(sorted(stale))}. Delete them; this directory "
              f"accumulates and an unread file is a check nobody is running.")
        return 2

    print((OUT / "version.txt").read_text().strip())
    print(f"python unicodedata {unicodedata.unidata_version}\n")

    failures = 0

    total, wrong = check_classes()
    print(f"break classes      {'OK' if not total else f'{total} DISAGREEMENTS'}")
    failures += total

    for bucket, codes in wrong.items():
        if codes:
            print(f"  Elixir says {bucket} for {len(codes)} codepoints we call something else")

    for label, diff in (
        ("ExtPict", check_extpict()),
        ("trim set", check_trim()),
        ("GB11 lookback", check_lookback()),
    ):
        print(f"{label:18} {'OK' if not diff else f'{len(diff)} DISAGREEMENTS'}")
        failures += len(diff)

    bad, total, examples = check_clusters()
    print(f"cluster boundaries {'OK' if not bad else f'{bad} of {total} DISAGREE'}")
    failures += bad
    for text, want, got in examples[:5]:
        print(f"    in  {[hex(ord(c)) for c in text]}")
        print(f"    otp {want}")
        print(f"    py  {got}")

    if "--tables" in sys.argv:
        print("\n# --- paste into services/name_rules.py ---\n")
        print(_literal("_EXT_PICT_RANGES", _ranges(_codepoints(OUT / "extpict.txt"))))
        print(_literal("_LAG_EXTEND", _ranges(set(wrong["A"]))))
        print(_literal("_LAG_CONTROL", _ranges(set(wrong["C"]))))

    if failures:
        print(
            f"\n{failures} disagreement(s). Re-run with --tables and paste the literals into "
            f"name_rules, then re-run the unit suite.",
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
