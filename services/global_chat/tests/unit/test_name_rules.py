"""Unit tests for the shared step-name rule (`services/name_rules.py`).

`yaml_utils` lives next to it and is tested from here too, so the shared
modules keep their tests in one place.
"""

import ast
import inspect
import unicodedata

import name_rules
import pytest
import yaml
from name_rules import (
    _TRIM_CHARS,
    MAX_NAME_LENGTH,
    PARITY_SOURCE,
    UNICODE_FLAG_ENV,
    _is_ext_pict,
    describe_rule,
    describe_rule_for_prompt,
    first_invalid_char,
    grapheme_clusters,
    grapheme_length,
    is_valid_name,
    normalize_for_lookup,
    normalize_nfc,
    sanitize_name,
    unicode_names_enabled,
)


@pytest.fixture
def ascii_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, "false")


@pytest.fixture
def unicode_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, "true")


# --- the flag ---------------------------------------------------------------


def test_unicode_is_off_when_the_flag_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNICODE_FLAG_ENV, raising=False)
    assert unicode_names_enabled() is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " True "])
def test_flag_accepts_the_usual_truthy_spellings(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, value)
    assert unicode_names_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "maybe"])
def test_flag_treats_anything_else_as_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, value)
    assert unicode_names_enabled() is False


# --- the ASCII rule ---------------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vérifier l'état", "Verifier letat"),
        ("O'Brien's Step", "OBriens Step"),
        ("Café München", "Cafe Munchen"),
        ("Fetch Data", "Fetch Data"),
        ("Valid Job-Name_123", "Valid Job-Name_123"),
        ("患者確認", ""),
        ("Проверка данных", ""),
    ],
)
def test_ascii_rule(raw: str, expected: str) -> None:
    assert sanitize_name(raw) == expected


@pytest.mark.usefixtures("ascii_mode")
def test_ascii_rule_no_longer_leaves_a_name_of_only_spaces() -> None:
    """`Проверка данных` used to sanitize to a single space, which is not a name."""
    assert sanitize_name("Проверка данных") == ""
    assert sanitize_name("ß straße") == "ss strasse"


# --- the Unicode rule -------------------------------------------------------


@pytest.mark.usefixtures("unicode_mode")
@pytest.mark.parametrize(
    "raw",
    [
        "Vérifier l'état",
        "O'Brien's Step",
        "患者確認",
        "Проверка данных",
        "ß straße",
        "رعاية المرضى",
        "Étape 1 (données)",
        "Étape 1: charger",
    ],
)
def test_unicode_rule_keeps_names_as_typed(raw: str) -> None:
    assert sanitize_name(raw) == raw


@pytest.mark.usefixtures("unicode_mode")
@pytest.mark.parametrize(
    "raw",
    [
        "a->b",           # nothing splits an edge key on "->"; it is a label
        "Import A/B",     # the page breadcrumb takes everything after the workflow
        "a|b",
        "a<b>c",
        "a#b",
        "Done ✅",
        "Ship it 🚢🇫🇷",
        "Étape « une »",
        'He said "go"',
        "50% & rising",
        "@mention",
    ],
)
def test_unicode_rule_allows_everything_that_is_not_a_control(raw: str) -> None:
    """The permissive rule is deliberately maximal.

    Apollo being stricter than Lightning is the silent-vandalism failure that
    issue #446 exists to prevent, so nothing but control characters is stripped.
    """
    assert first_invalid_char(raw) is None
    assert sanitize_name(raw) == raw
    assert is_valid_name(raw) is True


@pytest.mark.usefixtures("unicode_mode")
def test_unicode_rule_keeps_zero_width_joiner_sequences() -> None:
    """ZWJ is a format character — category C, but Lightning accepts it, so we must."""
    family = "Team \U0001f469\u200d\U0001f4bb"
    assert sanitize_name(family) == family


# --- control characters, both modes -----------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
@pytest.mark.parametrize("control", ["\x00", "\x01", "\x1b", "\x7f", "\x85", "\x9b"])
def test_control_characters_never_survive(monkeypatch: pytest.MonkeyPatch, mode: str, control: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    assert control not in sanitize_name(f"Fetch{control}Data")


@pytest.mark.parametrize("mode", ["false", "true"])
def test_nul_is_rejected_even_alone(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    assert sanitize_name("\x00") == ""


# --- NFC ---------------------------------------------------------------------


@pytest.mark.usefixtures("unicode_mode")
def test_decomposed_and_composed_forms_agree() -> None:
    """The same name typed two ways must come out identical, or lookups miss."""
    composed = "Vérifier"  # U+00E9
    decomposed = "Vérifier"  # e + combining acute

    assert composed != decomposed
    assert sanitize_name(composed) == sanitize_name(decomposed) == composed
    assert normalize_for_lookup(composed) == normalize_for_lookup(decomposed)


# --- validity helpers --------------------------------------------------------


@pytest.mark.usefixtures("ascii_mode")
def test_is_valid_name_tracks_the_active_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_valid_name("Fetch Data") is True
    assert is_valid_name("Vérifier l'état") is False

    monkeypatch.setenv(UNICODE_FLAG_ENV, "true")
    assert is_valid_name("Vérifier l'état") is True


@pytest.mark.usefixtures("ascii_mode")
def test_first_invalid_char_names_the_offender() -> None:
    assert first_invalid_char("Fetch Data") is None
    assert first_invalid_char("Fetch@Data") == "@"


# --- the prompt text ---------------------------------------------------------


def test_the_prompt_text_changes_with_the_mode() -> None:
    """The prompt and the sanitizer are built from the same rule, so it must move."""
    ascii_text = describe_rule(unicode_mode=False)
    unicode_text = describe_rule(unicode_mode=True)

    assert ascii_text != unicode_text
    assert "only unaccented English letters" in ascii_text
    assert "any script" in unicode_text
    assert "100" in describe_rule_for_prompt(unicode_mode=False)
    assert "unique" in describe_rule_for_prompt(unicode_mode=True)


# --- lookup normalization ----------------------------------------------------


def test_normalize_for_lookup_is_unicode_aware() -> None:
    """Non-Latin names used to fold to the empty string, which cross-matched everything."""
    assert normalize_for_lookup("患者確認") == "患者確認"
    assert normalize_for_lookup("Проверка данных") == "проверка-данных"
    assert normalize_for_lookup("患者確認") != normalize_for_lookup("データ送信")


def test_normalize_for_lookup_keeps_the_old_latin_behaviour() -> None:
    assert normalize_for_lookup("Fetch Patients") == "fetch-patients"
    assert normalize_for_lookup("--Fetch/Patients--") == "fetch-patients"
    assert normalize_for_lookup("") == ""


def test_normalize_for_lookup_keeps_combining_marks() -> None:
    """Devanagari matras are Unicode marks, not letters — they must not become hyphens."""
    assert normalize_for_lookup("रोगी की जाँच") == "रोगी-की-जाँच"


# --- length cap ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_cap_counts_graphemes(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    assert grapheme_length(sanitize_name("a" * 200)) == MAX_NAME_LENGTH


@pytest.mark.usefixtures("unicode_mode")
def test_grapheme_length_counts_user_perceived_characters() -> None:
    assert grapheme_length("abc") == len("abc")
    assert grapheme_length("e\u0301") == 1  # e + combining acute
    assert grapheme_length("\U0001f469\u200d\U0001f4bb") == 1  # ZWJ sequence
    assert grapheme_length("\U0001f1eb\U0001f1f7") == 1  # flag, two regional indicators
    assert grapheme_length("\U0001f44d\U0001f3fd") == 1  # emoji + skin tone
    # Devanagari conjuncts are covered by the Elixir parity table below
    # instead — they sit on the GB9c divergence, so a hand-written expectation
    # here would just duplicate that table and drift from it.


#: A grapheme NFC cannot collapse into a single codepoint. `e` + combining
#: acute is no use for testing truncation: NFC composes it to `é` before the
#: cut ever happens, so it never exercises a multi-codepoint cluster.
SCOTLAND_FLAG = "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"
WOMAN_TECHNOLOGIST = "\U0001F469\u200d\U0001F4BB"


@pytest.mark.usefixtures("unicode_mode")
@pytest.mark.parametrize("cluster", [SCOTLAND_FLAG, WOMAN_TECHNOLOGIST, "\U0001F44D\U0001F3FD"])
def test_cap_does_not_split_a_grapheme(cluster: str) -> None:
    """Cutting inside a cluster corrupts it — an orphaned tag or a bare joiner.

    Each of these stays multi-codepoint through NFC, so the cut is real.
    """
    assert len(cluster) > 1, "NFC collapsed the fixture; it no longer tests anything"

    capped = sanitize_name(cluster * 200)

    assert grapheme_length(capped) == MAX_NAME_LENGTH
    assert capped == cluster * MAX_NAME_LENGTH
    # Nothing left dangling at the cut.
    assert grapheme_clusters(capped)[-1] == cluster


@pytest.mark.usefixtures("unicode_mode")
def test_nfc_composition_before_the_cap() -> None:
    """The old fixture, kept to pin down why it was the wrong test."""
    assert sanitize_name("e\u0301" * 200) == "\u00e9" * MAX_NAME_LENGTH


@pytest.mark.usefixtures("unicode_mode")
def test_cap_counts_emoji_as_one_each() -> None:
    capped = sanitize_name("\U0001f469\u200d\U0001f4bb" * 200)
    assert grapheme_length(capped) == MAX_NAME_LENGTH


# --- parity with Elixir's String.length/1 -------------------------------------
#
# Ecto's `validate_length` counts graphemes with `String.length/1`, so that is
# the authority — not UAX #29, which Elixir deviates from in two places we
# deliberately copy. Every number below was generated by running Elixir 1.18.3
# over the same codepoint sequences.
#
# The standing check is `tools/unicode_parity`, not a figure quoted here: it
# puts every codepoint in 0x0..0x10FFFF in the same break class as Elixir and
# compares cluster boundaries over the corpus `probe.exs` generates. There is
# no known clustering divergence; if one appears, add the shape here rather
# than widening the assertion.

ELIXIR_PARITY = [
    ("ascii", [0x0061, 0x0062, 0x0063], 3),
    ("e+combining acute", [0x0065, 0x0301], 1),
    ("ExtPict ZWJ ExtPict", [0x1F469, 0x200D, 0x1F4BB], 1),
    ("a ZWJ b (GB11 must NOT join)", [0x0061, 0x200D, 0x0062], 2),
    ("a ZWJ combining mark (plain lead: mark attaches)", [0x0061, 0x200D, 0x0301], 1),
    ("ExtPict ZWJ combining mark (emoji run ends at the joiner)", [0x00A9, 0x200D, 0x0301], 2),
    ("ExtPict ZWJ combining mark x200", [0x00A9, 0x200D, 0x0301] * 200, 400),
    ("woman ZWJ combining mark", [0x1F469, 0x200D, 0x0301], 2),
    ("ExtPict Extend ZWJ combining mark", [0x00A9, 0x0301, 0x200D, 0x0301], 2),
    ("ExtPict ZWJ VS16", [0x00A9, 0x200D, 0xFE0F], 2),
    ("ExtPict ZWJ skintone", [0x00A9, 0x200D, 0x1F3FD], 2),
    ("ExtPict ZWJ ZWJ", [0x00A9, 0x200D, 0x200D], 2),
    ("scotland flag tag seq", [0x1F3F4, 0xE0067, 0xE0062, 0xE0073, 0xE0063, 0xE0074, 0xE007F], 1),
    ("15x scotland flag", [0x1F3F4, 0xE0067, 0xE0062, 0xE0073, 0xE0063, 0xE0074, 0xE007F] * 15, 15),
    ("FR flag (2 RI)", [0x1F1EB, 0x1F1F7], 1),
    ("3 RI", [0x1F1EB, 0x1F1F7, 0x1F1EB], 2),
    ("4 RI", [0x1F1EB, 0x1F1F7, 0x1F1EB, 0x1F1F7], 2),
    ("thumbsup + skintone", [0x1F44D, 0x1F3FD], 1),
    ("devanagari namaste", [0x0928, 0x092E, 0x0938, 0x094D, 0x0924, 0x0947], 4),
    ("indic conjunct ka virama ssa", [0x0915, 0x094D, 0x0937], 2),
    ("CRLF", [0x000D, 0x000A], 1),
    ("hangul L V T", [0x1100, 0x1161, 0x11A8], 1),
    ("hangul LV + T", [0xAC00, 0x11A8], 1),
    ("keycap 1", [0x0031, 0xFE0F, 0x20E3], 1),
    ("arabic number sign prepend", [0x0600, 0x0661], 1),
    ("zanabazar prepend 11A3A x150", [0x11A3A, 0x0061] * 150, 150),
    ("masaram prepend 11D46 x150", [0x11D46, 0x0061] * 150, 150),
    ("kawi prepend 11F02 x150", [0x11F02, 0x0061] * 150, 150),
    ("tamil ka virama", [0x0B95, 0x0BCD], 1),
    ("family ZWJ", [0x1F468, 0x200D, 0x1F469, 0x200D, 0x1F467], 1),
    ("heart + VS16", [0x2764, 0xFE0F], 1),
    ("trailing lone ZWJ", [0x0061, 0x200D], 1),
    ("leading ZWJ", [0x200D, 0x0061], 2),
    ("ExtPict ZWJ non-ExtPict", [0x1F469, 0x200D, 0x0062], 2),
    ("spacingmark devanagari aa", [0x0915, 0x093E], 1),
    ("thai sara i", [0x0E01, 0x0E31], 1),
    ("myanmar non-spacingmark Mc (1063)", [0x1000, 0x1063], 2),
    ("myanmar non-spacingmark Mc (109C)", [0x1000, 0x109C], 2),
    ("kawi vowel (post-Unicode-14 mark)", [0x11F00, 0x11F01], 1),
    ("kawi sign 11F41 attaches", [0x11F04, 0x11F41], 1),
    ("nag mundari 1E4EC attaches", [0x1E4D0, 0x1E4EC], 1),
    ("egyptian hieroglyph control 13439", [0x13000, 0x13439, 0x0301], 3),
    ("RI + extend", [0x1F1EB, 0xFE0F, 0x1F1F7], 2),
    ("emoji + VS + ZWJ + emoji", [0x1F468, 0xFE0F, 0x200D, 0x1F469], 1),
    ("digit + tag", [0x0031, 0xE0031], 1),
    ("100x a-ZWJ-b", [0x0061, 0x200D, 0x0062] * 100, 200),
]


@pytest.mark.parametrize(("name", "codepoints", "expected"), ELIXIR_PARITY)
def test_grapheme_length_matches_elixir(name: str, codepoints: list, expected: int) -> None:
    assert grapheme_length("".join(map(chr, codepoints))) == expected, name


@pytest.mark.parametrize(("name", "codepoints", "expected"), ELIXIR_PARITY)
def test_cap_never_exceeds_what_elixir_would_count(
    name: str, codepoints: list, expected: int,
) -> None:
    """Undercounting is the failure that matters: it emits a name Ecto rejects."""
    del expected
    capped = sanitize_name("".join(map(chr, codepoints)) * 40, unicode_mode=True)
    assert grapheme_length(capped) <= MAX_NAME_LENGTH, name


def test_the_regressions_the_reviews_found() -> None:
    """`a<ZWJ>b` must not join, a flag tag sequence must not be seven, and an
    emoji ZWJ run must end at the joiner when a plain mark follows."""
    # GB11 joins across a ZWJ only when both sides are pictographic. Two plain
    # letters are not, so this is two graphemes, not one.
    assert grapheme_clusters("a\u200db") == ["a\u200d", "b"]
    assert grapheme_clusters("a\u200db" * 100) == ["a\u200d", "b"] * 100

    # The tag characters are Extend, so the whole flag sequence is one grapheme.
    assert grapheme_clusters(SCOTLAND_FLAG) == [SCOTLAND_FLAG]
    assert grapheme_clusters(SCOTLAND_FLAG * 15) == [SCOTLAND_FLAG] * 15

    # Elixir ends an emoji ZWJ run at the joiner unless a pictograph follows,
    # so this is two graphemes per copy, not one. Counting it as one meant a
    # 200-grapheme name went out under a 100-grapheme cap.
    assert grapheme_clusters("\u00a9\u200d\u0301") == ["\u00a9\u200d", "\u0301"]
    copies = 200
    assert grapheme_length("\u00a9\u200d\u0301" * copies) == copies * len(["\u00a9\u200d", "\u0301"])
    assert grapheme_length(
        sanitize_name("\u00a9\u200d\u0301" * copies, unicode_mode=True),
    ) == MAX_NAME_LENGTH

    # ...but with a plain lead the mark still attaches, per GB9.
    assert grapheme_clusters("a\u200d\u0301") == ["a\u200d\u0301"]


def test_prepend_families_are_recognised() -> None:
    """`regex` misses these, which made it truncate at half the real limit."""
    for prepend in ("\U00011A3A", "\U00011A84", "\U00011D46", "\U00011F02", "\u0600"):
        assert grapheme_clusters(prepend + "a") == [prepend + "a"]
        copies = 150
        assert grapheme_length((prepend + "a") * copies) == copies
        assert grapheme_length(
            sanitize_name((prepend + "a") * copies, unicode_mode=True),
        ) == MAX_NAME_LENGTH


def test_post_unicode_14_characters_are_classified() -> None:
    """Python 3.11 ships Unicode 14, so these look unassigned without the lag table."""
    assert unicodedata.category("\U00011F41") == "Cn", "python caught up; the lag table can shrink"
    assert grapheme_clusters("\U00011F04\U00011F41") == ["\U00011F04\U00011F41"]
    assert grapheme_clusters("\U0001E4D0\U0001E4EC") == ["\U0001E4D0\U0001E4EC"]
    # Egyptian hieroglyph format controls break on both sides.
    assert grapheme_clusters("\U00013000\U00013439\u0301") == [
        "\U00013000", "\U00013439", "\u0301",
    ]


def test_there_is_no_regex_dependency() -> None:
    """Which algorithm runs must not depend on transitive resolution.

    `regex` is spec-correct, which is why it is wrong here — see `name_rules`.
    """
    tree = ast.parse(inspect.getsource(name_rules))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert imported == {"os", "unicodedata"}, imported


# --- trimming -----------------------------------------------------------------


def test_trim_set_is_exactly_what_elixir_strips() -> None:
    """Brute-forced against Elixir 1.18.3 over the whole codepoint space.

    Python's bare `.strip()` also eats U+001C-U+001F, which are not Unicode
    White_Space. Trimming a different set from Lightning would mean the two
    disagree about a name's identity, and step lookup would silently miss.
    """
    elixir_trims = {
        0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
        0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
        0x2007, 0x2008, 0x2009, 0x200A, 0x2028, 0x2029, 0x202F,
        0x205F, 0x3000,
    }
    assert {ord(c) for c in _TRIM_CHARS} == elixir_trims

    python_only = {c for c in range(0x110000) if chr(c).strip() == "" and c != 0} - elixir_trims
    assert python_only == {0x1C, 0x1D, 0x1E, 0x1F}
    assert not (python_only & {ord(c) for c in _TRIM_CHARS})


@pytest.mark.usefixtures("unicode_mode")
@pytest.mark.parametrize("space", ["\xa0", "\u2003", "\u3000", "\u205f", " "])
def test_unicode_whitespace_is_trimmed(space: str) -> None:
    assert sanitize_name(f"{space}Fetch Data{space}") == "Fetch Data"


# --- surrogates ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_lone_surrogates_are_rejected(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """A lone surrogate cannot be encoded as UTF-8, so it must never reach Lightning."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)
    name = "Fetch\ud800Data\udfff"

    cleaned = sanitize_name(name)

    assert cleaned == "FetchData"
    cleaned.encode("utf-8")  # would raise if a surrogate survived


# --- case folding -------------------------------------------------------------


def test_lookup_folds_case_rather_than_lowercasing() -> None:
    """`.lower()` leaves these pairs distinct, so the lookups used to miss."""
    assert normalize_for_lookup("ΣΙΣ") == normalize_for_lookup("σις")
    assert normalize_for_lookup("ΟΔΟΣ") == normalize_for_lookup("οδος")
    assert normalize_for_lookup("STRASSE") == normalize_for_lookup("straße")


# --- Extended_Pictographic ----------------------------------------------------

#: What tools/unicode_parity produced against PARITY_SOURCE. These move only
#: when the tables are regenerated against a different Elixir or Python.
EXT_PICT_CODEPOINTS = 3537
LAG_EXTEND_RANGES = 12
LAG_CONTROL_RANGES = 7


def test_extpict_is_not_over_broad() -> None:
    """The bug a codepoint-bucket sweep structurally cannot find.

    ExtPict is not a break class, so classifying every codepoint into A/P/C/O
    passes regardless of how wrong this set is. It only shows up either side of
    a ZWJ. The hand-written ranges claimed hundreds of codepoints too many by
    collapsing sparse sets into solid blocks.
    """
    # U+2713 sits inside the old (0x2600, 0x27BF) block and is not pictographic.
    assert not _is_ext_pict(0x2713), "CHECK MARK is not Extended_Pictographic"
    assert not _is_ext_pict(0x219A), "arrows in the 0x2190 block are not pictographic"
    assert _is_ext_pict(0x2764), "HEAVY BLACK HEART is"
    assert _is_ext_pict(0x1F600)


def test_a_non_pictograph_does_not_join_across_a_zwj() -> None:
    """`✓<ZWJ><emoji>` is two graphemes to Elixir; calling it one shipped a
    200-grapheme name under a 100-grapheme cap."""
    assert grapheme_clusters("✓‍\U0001F600") == ["✓‍", "\U0001F600"]
    copies = 100
    assert grapheme_length("✓‍\U0001F600" * copies) == copies * 2

    # And the other direction: a mark after a non-pictograph's ZWJ still
    # attaches under GB9, so this is one grapheme, and truncating it early
    # would have cut a name Lightning accepts.
    assert grapheme_clusters("✓‍́") == ["✓‍́"]


def test_the_extpict_set_matches_the_recorded_probe() -> None:
    """Canary for Elixir moving forward.

    Regenerating the tables against a newer Elixir changes these sizes, which
    fails here until PARITY_SOURCE is updated too.
    """
    assert PARITY_SOURCE == {"elixir": "1.18.3", "otp": "27", "python_unicodedata": "14.0.0"}
    assert unicodedata.unidata_version == PARITY_SOURCE["python_unicodedata"], (
        "Python's Unicode version moved; re-run tools/unicode_parity and update PARITY_SOURCE"
    )
    # Pinned to what tools/unicode_parity produced against PARITY_SOURCE.
    assert sum(b - a + 1 for a, b in name_rules._EXT_PICT_RANGES) == EXT_PICT_CODEPOINTS
    assert len(name_rules._LAG_EXTEND) == LAG_EXTEND_RANGES
    assert len(name_rules._LAG_CONTROL) == LAG_CONTROL_RANGES


# --- GB11 lookback ------------------------------------------------------------


def test_the_emoji_run_lookback_crosses_a_spacing_mark() -> None:
    """UAX #29 says Extend only; Elixir also crosses SpacingMark."""
    heart, zwj, emoji = "❤", "‍", "\U0001F600"

    assert grapheme_clusters(f"{heart}\u0903{zwj}{emoji}") == [f"{heart}\u0903{zwj}{emoji}"]
    assert grapheme_clusters(f"{heart}́{zwj}{emoji}") == [f"{heart}́{zwj}{emoji}"]
    assert grapheme_clusters(f"{heart}́\u0903{zwj}{emoji}") == [
        f"{heart}́\u0903{zwj}{emoji}",
    ]

    # ...but not an ordinary character, and not a non-SpacingMark Mc.
    assert grapheme_clusters(f"{heart}a{zwj}{emoji}") == [heart, f"a{zwj}", emoji]
    assert grapheme_clusters(f"{heart}ၣ{zwj}{emoji}") == [heart, f"ၣ{zwj}", emoji]


# --- line and paragraph separators --------------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
@pytest.mark.parametrize("separator", ["\u2028", "\u2029"])
def test_line_separators_are_rejected(
    monkeypatch: pytest.MonkeyPatch, mode: str, separator: str,
) -> None:
    """PyYAML writes them literally and indents the continuation; yamerl, which
    is what Lightning parses with, does not fold that back, so the stored name
    grows YAML indentation inside it."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)

    cleaned = sanitize_name(f"Fetch{separator}Data")

    assert separator not in cleaned
    assert cleaned == "Fetch Data"
    assert not is_valid_name(f"a{separator}b")


def test_a_name_with_a_line_separator_survives_the_yaml_round_trip() -> None:
    """The check PyYAML-only tests are blind to: it reads its own output back
    correctly, so the damage is invisible from this side."""
    name = sanitize_name("Fetch\u2028Data", unicode_mode=True)
    dumped = yaml.dump({"name": name}, allow_unicode=True)

    assert "\u2028" not in dumped

    # `str.split("\n")` does not split on U+2028 but `splitlines` does, which is
    # the whole point: PyYAML writes the separator literally and indents the
    # continuation, and a parser that treats it as a line break (yamerl, which
    # is what Lightning uses) then reads that indentation back into the name.
    # Splitting on "\n" made this assertion always pass, and it also fired on
    # any name long enough for PyYAML to wrap.
    assert len(dumped.splitlines()) == len(dumped.rstrip("\n").split("\n"))


def test_the_line_separator_assertion_would_catch_the_real_damage() -> None:
    """Guards the test above: show the check fails on an unsanitised name."""
    dumped = yaml.dump({"name": "Fetch\u2028Data"}, allow_unicode=True)

    assert "\u2028" in dumped
    assert len(dumped.splitlines()) != len(dumped.rstrip("\n").split("\n"))


# --- normalisation ------------------------------------------------------------


@pytest.mark.parametrize("mode", ["false", "true"])
def test_sanitized_names_are_fixed_points_of_normalisation(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """A name that has been through `sanitize_name` normalises to itself, which
    is what `is_valid_name` stakes its answer on."""
    monkeypatch.setenv(UNICODE_FLAG_ENV, mode)

    for text in (
        "Vérifier l'état",
        "\u0995\u09c7\u09be",
        "A\u0302\u200c\u0323",
        "患者確認",
        # Leading and trailing whitespace matter here rather than being noise:
        # trimming is what can uncover a mark that had nothing to compose onto.
        " \u09cb",
        "\t\u09cb ",
        "  \u0995\u094b",
        " Vérifier l'état ",
    ):
        cleaned = sanitize_name(text)
        assert sanitize_name(cleaned) == cleaned
        assert normalize_nfc(cleaned) == cleaned


@pytest.mark.usefixtures("unicode_mode")
def test_trimming_does_not_leave_a_mark_uncomposed() -> None:
    """Trimming happens after normalising, so it can leave behind a boundary
    that has not been normalised. Repeat until it settles, or the sanitiser
    returns a name it would then call invalid."""
    assert sanitize_name(" \u09cb") == "\u09cb"
    assert is_valid_name(sanitize_name(" \u09cb"))
