r"""Single source of truth for which characters a workflow step name may contain.

Lightning validates step names on its side and Apollo sanitises them on this
side. The two rules have to agree: if Apollo strips a character Lightning would
have accepted, Apollo silently renames a step the user deliberately named; if
Apollo emits a character Lightning rejects, the workflow fails to save. Of the
two, Apollo being *stricter* is the worse failure -- that is the silent
vandalism issue #446 exists to stop -- so the permissive rule below is
deliberately maximal.

Lightning is lifting its restriction (Lightning#4577) from ASCII-only to
"anything except control characters". The two releases cannot ship at the same
instant, so the rule here is switchable at runtime:

  APOLLO_UNICODE_STEP_NAMES=false  (default) -- today's ASCII-only behaviour,
      matching Lightning's current ``~r/^[a-zA-Z0-9_\- ]*$/``.
  APOLLO_UNICODE_STEP_NAMES=true            -- anything except control
      characters. Letters and marks from any script, all punctuation and
      symbols, emoji, ``/``, ``:``, ``>``, ``&``, quotes and apostrophes.

Deploy Apollo first with the default, flip the flag once Lightning ships.

Both modes reject the same set, and nothing else is ever rejected in permissive
mode:

  C0            U+0000-U+001F  (NUL included)
  DEL           U+007F
  C1            U+0080-U+009F
  noncharacters U+FFFE, U+FFFF
  surrogates    U+D800-U+DFFF   (cannot be encoded as UTF-8 at all)
  separators    U+2028, U+2029  (do not survive the YAML round trip)

A NUL byte in a name crashes the Postgres insert on Lightning's side
(Lightning#4893), so it is never permitted regardless of which rule is active.

Both modes normalise to NFC and cap the name at 100 *graphemes*, counted the
way Elixir counts them (see the grapheme section below). Ecto's
``validate_length`` counts graphemes, so counting codepoints here would let a
name through that Lightning then rejects.

On normalisation: Lightning's ``main`` still carries the ASCII-only regex at
``job.ex`` and does not normalise. The NFC normalisation this module is
matching is on Lightning's ``4577-unicode-step-names`` branch, unmerged at the
time of writing -- so treat "Lightning normalises to NFC" as the agreed plan,
not as shipped behaviour, and re-check the branch before flipping the flag.
Step lookup matches names as text, so if the two sides ever disagree on the
normal form, a lookup for a name containing an accent silently misses.
"""

import os
import unicodedata

#: Environment variable that selects the rule. Unset means the ASCII rule.
UNICODE_FLAG_ENV = "APOLLO_UNICODE_STEP_NAMES"

#: Values that turn the Unicode rule on. Anything else (including unset) is off.
_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})

#: Permitted in both modes, alongside the letters and digits.
BASE_PUNCTUATION = " -_"

#: ASCII letters and digits, the whole alphabet of the restrictive rule.
_ASCII_ALNUM = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
)

#: Everything the restrictive rule permits.
_ASCII_ALLOWED = _ASCII_ALNUM | frozenset(BASE_PUNCTUATION)

#: Unicode general categories that count as "a letter, mark or digit".
#: Used only by the lookup normalizer, not by the name rule.
_LETTER_MARK_DIGIT = ("L", "M", "N")

#: Longest name Lightning will store, counted in graphemes (Ecto's
#: ``validate_length`` counts graphemes, and Lightning's client matches it).
MAX_NAME_LENGTH = 100

# How many times sanitize_name may re-trim and re-normalise before giving up.
# Two passes settle every case found so far; the rest is margin.
_SANITIZE_PASSES = 4

#: Longest edge key. An edge label is ``source->target``, so two names at the
#: limit would otherwise make a key over twice the length of anything else in
#: the document.
MAX_EDGE_KEY_LENGTH = MAX_NAME_LENGTH * 2 + len("->")

#: Letters NFKD cannot decompose, so under the ASCII rule they would vanish and
#: take the word with them (``straße`` -> ``strae``). Spelled out instead.
#:
#: DELIBERATE DEVIATION: this table is new, not part of the long-standing ASCII
#: behaviour. It only affects characters that used to disappear entirely, so
#: the result is strictly more readable, but it does mean ASCII-mode output for
#: those letters differs from what Apollo produced before this change.
_ASCII_TRANSLITERATIONS = str.maketrans({
    "ß": "ss", "ẞ": "SS",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
    "ø": "o", "Ø": "O",
    "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "TH",
    "ł": "l", "Ł": "L",
    "ı": "i", "ŋ": "n", "Ŋ": "N",  # noqa: RUF001 - dotless i is the character being mapped
})

#: The control set rejected in every mode, and the only thing the permissive
#: rule rejects at all.
_C0 = range(0x20)  # NUL through US
_DEL = 0x7F
_C1 = range(0x80, 0xA0)
_NONCHARACTERS = frozenset({0xFFFE, 0xFFFF})

#: Lone surrogates. Python will hold one in a str (a YAML or JSON payload can
#: carry a bare \ud800), but it cannot be encoded as UTF-8, so letting one
#: through would hand Lightning a name it cannot store.
_SURROGATES = range(0xD800, 0xE000)

#: LINE SEPARATOR and PARAGRAPH SEPARATOR. Not control characters by category,
#: but they cannot survive the round trip: PyYAML with ``allow_unicode=True``
#: writes U+2028 literally and then indents the continuation, and ``yamerl``,
#: which is what Lightning parses with, does not fold that back. A name goes in
#: at 11 graphemes and comes out of Lightning at 17 with six spaces of YAML
#: indentation inside it. PyYAML reads its own output back correctly, so this
#: is invisible from this side of the wire. Lightning rejects them too.
_LINE_SEPARATORS = frozenset({0x2028, 0x2029})

#: Exactly what Elixir's `String.trim/1` strips, verified by brute-forcing the
#: whole codepoint space against Elixir 1.18.3: the 25 Unicode White_Space
#: characters. Python's bare `str.strip()` also eats U+001C-U+001F, which are
#: not White_Space, so trimming with an explicit set is what keeps Apollo and
#: Lightning agreeing on a name's identity.
_TRIM_CHARS = "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"

#: What the generated tables below were probed from. `tools/unicode_parity`
#: regenerates them; if you re-run it against a different Elixir, update this
#: too -- a unit test pins it, so a silent regeneration fails loudly.
#:
#: Python moving forward is benign: it only ever makes this module overcount,
#: which truncates early. Elixir moving forward is the dangerous direction,
#: because a script it learns to cluster and this module does not is an
#: undercount, and an undercount ships a name Ecto rejects.
PARITY_SOURCE = {"elixir": "1.18.3", "otp": "27", "python_unicodedata": "14.0.0"}


def unicode_names_enabled() -> bool:
    """Return True when the Unicode-permissive rule is active.

    Read at call time rather than import time so tests (and a redeploy that
    only changes the environment) do not need the module reloaded.
    """
    return os.getenv(UNICODE_FLAG_ENV, "false").strip().lower() in _TRUTHY


def _is_forbidden(char: str) -> bool:
    """True for the characters rejected in every mode.

    C0 (U+0000-U+001F, NUL included), DEL (U+007F), C1 (U+0080-U+009F), the
    noncharacters U+FFFE and U+FFFF, lone surrogates (which cannot be encoded
    as UTF-8 at all), and U+2028/U+2029 (which do not survive the YAML round
    trip into Lightning). Nothing else is ever rejected under the permissive
    rule -- deliberately, because Apollo being stricter than Lightning means
    Apollo renames names Lightning would have accepted.

    Note this is a codepoint test, not a general-category test. Category ``C``
    also covers format characters such as ZWJ (U+200D), which emoji sequences
    need, and private-use and unassigned codepoints, all of which Lightning
    accepts.
    """
    code = ord(char)
    return (
        code in _C0
        or code == _DEL
        or code in _C1
        or code in _NONCHARACTERS
        or code in _SURROGATES
        or code in _LINE_SEPARATORS
    )


def is_control_char(char: str) -> bool:
    """True for a character rejected in every mode. See `_is_forbidden`."""
    return _is_forbidden(char)


def is_allowed_char(char: str, unicode_mode: bool | None = None) -> bool:
    """Return True if `char` may appear verbatim in a step name under the active rule."""
    if unicode_mode is None:
        unicode_mode = unicode_names_enabled()
    if _is_forbidden(char):
        return False
    return unicode_mode or char in _ASCII_ALLOWED


# Grapheme clustering. Ecto's `validate_length` counts graphemes, so the length
# cap has to as well: undercounting lets Apollo emit a name Lightning rejects,
# and overcounting truncates a name Lightning would have accepted, cutting
# mid-cluster and leaving an orphaned combining mark behind.
#
# The authority is Elixir's `String.length/1`, because that is what Ecto calls.
# So the target is not "correct per UAX #29" but "identical to Elixir", and the
# two are not the same thing. Elixir deviates from the spec in two places that
# matter here, and this implementation deliberately copies both:
#
#   * It does not implement GB9c, the Unicode 15.1 Indic conjunct rule, so
#     `क` + virama + `ष` is two graphemes to Elixir and one to the spec.
#   * It ends an emoji ZWJ run *at* the joiner unless another pictograph
#     follows, so `©<ZWJ><combining acute>` is two graphemes to Elixir and one
#     to the spec (which would attach the mark under GB9).
#
# Everything is hand-written here on purpose. The `regex` module's `\X` is
# spec-correct, and the target is OTP, not the spec -- so `\X` disagrees with
# OTP in *both* directions:
#
#   * It undercounts on the two deviations named above. `©<ZWJ><mark>` a
#     hundred times is 200 graphemes to OTP and 100 to `\X`, so a name twice
#     the cap passes the cap. This is the dangerous direction, because the name
#     then fails Ecto's `validate_length` on Lightning's side.
#   * It overcounts on U+11A3A, which it does not treat as GCB=Prepend. Here
#     `\X` is not "spec-correct but different", it is simply wrong: GB9b says
#     no break, and the spec, OTP and this module all agree. An overcount
#     truncates a name Lightning would have accepted.
#
# Over the corpus `tools/unicode_parity` generates that is 184 undercounts and
# 132 overcounts, against none in either direction here. Read those figures as
# "both directions occur", not as a rate: the 132 are one codepoint multiplied
# by the corpus cross-product, and the corpus contains only as many of each
# shape as it was built to contain.
#
# `regex` was also never a declared dependency -- it arrived transitively
# through nltk -- so which algorithm ran would have depended on resolution.
#
# Re-derive with `elixir probe.exs && python3 check.py`. Two earlier revisions
# of this comment quoted figures from corpora that no longer existed, and one
# had the direction backwards.
#
# Verified by tools/unicode_parity against Elixir 1.18.3. Re-run it whenever
# either side's Unicode version moves.

_ZWJ = "\u200d"
_CR = "\r"
_LF = "\n"

_REGIONAL_INDICATOR = range(0x1F1E6, 0x1F200)

#: GCB=Extend characters that are not Mn/Me by general category.
_OTHER_GRAPHEME_EXTEND = frozenset(
    {
        0x09BE, 0x09D7, 0x0B3E, 0x0B57, 0x0BBE, 0x0BD7, 0x0CC2, 0x0CD5, 0x0CD6,
        0x0D3E, 0x0D57, 0x0DCF, 0x0DDF, 0x1B35, 0x200C, 0x302E, 0x302F, 0xFF9E,
        0xFF9F, 0x1133E, 0x11357, 0x114B0, 0x115AF, 0x11930, 0x1D165, 0x1D16E,
        0x1D16F, 0x1D170, 0x1D171, 0x1D172,
    },
)

#: Tag characters (GCB=Extend despite being format characters). These are what
#: make the Scotland/Wales/England flag sequences a single grapheme.
_TAGS = range(0xE0020, 0xE0080)

#: Emoji skin-tone modifiers. General category Sk, but GCB=Extend.
_SKIN_TONES = range(0x1F3FB, 0x1F400)

#: GCB=Prepend.
_PREPEND = frozenset(
    {
        0x0600, 0x0601, 0x0602, 0x0603, 0x0604, 0x0605, 0x06DD, 0x070F, 0x0890,
        0x0891, 0x08E2, 0x0D4E, 0x110BD, 0x110CD, 0x111C2, 0x111C3, 0x1193F,
        0x11941, 0x11A3A, 0x11A84, 0x11A85, 0x11A86, 0x11A87, 0x11A88, 0x11A89,
        0x11D46, 0x11F02,
    },
)

#: Mc characters that are NOT GCB=SpacingMark. GraphemeBreakProperty.txt lists
#: them nowhere else, so they fall through to GCB=Other -- not Extend.
_NOT_SPACING_MARK = frozenset(
    {
        0x102B, 0x102C, 0x1038, 0x1062, 0x1063, 0x1064, 0x1067, 0x1068, 0x1069,
        0x106A, 0x106B, 0x106C, 0x106D, 0x1083, 0x1087, 0x1088, 0x1089, 0x108A,
        0x108B, 0x108C, 0x108F, 0x109A, 0x109B, 0x109C, 0x1A61, 0x1A63, 0x1A64,
        0xAA7B, 0xAA7D, 0x11720, 0x11721,
    },
)

#: Lo characters that ARE GCB=SpacingMark.
_EXTRA_SPACING_MARK = frozenset({0x0E33, 0x0EB3})

#: Hangul jamo, for GB6/GB7/GB8.
_HANGUL_L = (range(0x1100, 0x1160), range(0xA960, 0xA97D))
_HANGUL_V = (range(0x1160, 0x11A8), range(0xD7B0, 0xD7C7))
_HANGUL_T = (range(0x11A8, 0x1200), range(0xD7CB, 0xD7FC))
_HANGUL_SYLLABLES = range(0xAC00, 0xD7A4)

#: Extended_Pictographic, for GB11. Generated from Elixir, not hand-written:
#: ExtPict is not a break class, so a codepoint-bucket sweep cannot check it
#: and an over-broad range here is invisible to that test. The earlier
#: hand-written version collapsed sparse sets into solid blocks and claimed
#: hundreds of codepoints too many -- U+2713 CHECK MARK among them, which made
#: `✓<ZWJ><emoji>` one grapheme here and two in Elixir. (The exact count is not
#: quoted because that table is gone and nothing in the tree reproduces it;
#: `check.py` compares this table against Elixir directly instead.)
#: Regenerate with tools/unicode_parity/probe.exs (see extpict).
_EXT_PICT_RANGES = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C),
    (0x2049, 0x2049), (0x2122, 0x2122), (0x2139, 0x2139),
    (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B),
    (0x2328, 0x2328), (0x2388, 0x2388), (0x23CF, 0x23CF),
    (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2),
    (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0),
    (0x25FB, 0x25FE), (0x2600, 0x2605), (0x2607, 0x2612),
    (0x2614, 0x2685), (0x2690, 0x2705), (0x2708, 0x2712),
    (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D),
    (0x2721, 0x2721), (0x2728, 0x2728), (0x2733, 0x2734),
    (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C),
    (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757),
    (0x2763, 0x2767), (0x2795, 0x2797), (0x27A1, 0x27A1),
    (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935),
    (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50),
    (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299), (0x1F000, 0x1F0FF),
    (0x1F10D, 0x1F10F), (0x1F12F, 0x1F12F), (0x1F16C, 0x1F171),
    (0x1F17E, 0x1F17F), (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A),
    (0x1F1AD, 0x1F1E5), (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F),
    (0x1F249, 0x1F3FA), (0x1F400, 0x1F53D), (0x1F546, 0x1F64F),
    (0x1F680, 0x1F6FF), (0x1F774, 0x1F77F), (0x1F7D5, 0x1F7FF),
    (0x1F80C, 0x1F80F), (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F),
    (0x1F888, 0x1F88F), (0x1F8AE, 0x1F8FF), (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945), (0x1F947, 0x1FAFF), (0x1FC00, 0x1FFFD),
)


#: Codepoints assigned after the Unicode version Python's `unicodedata` ships
#: (3.11 carries Unicode 14.0; Elixir 1.18.3 is on a later one). Without these
#: they look unassigned here, fall through to GCB=Other, and the count drifts
#: from Elixir on any name using a script added since -- Kawi, Nag Mundari, the
#: Egyptian hieroglyph controls.
#: Regenerate with tools/unicode_parity/probe.exs (see classmap).
_LAG_EXTEND = (
    (0x0CF3, 0x0CF3), (0x0ECE, 0x0ECE), (0x10EFD, 0x10EFF),
    (0x11241, 0x11241), (0x11F00, 0x11F01), (0x11F03, 0x11F03),
    (0x11F34, 0x11F3A), (0x11F3E, 0x11F42), (0x13440, 0x13440),
    (0x13447, 0x13455), (0x1E08F, 0x1E08F), (0x1E4EC, 0x1E4EF),
)

_LAG_CONTROL = (
    (0x2065, 0x2065), (0xFFF0, 0xFFF8), (0x13439, 0x1343F),
    (0xE0000, 0xE0000), (0xE0002, 0xE001F), (0xE0080, 0xE00FF),
    (0xE01F0, 0xE0FFF),
)

# Boundary classes, named so the rule table below reads like UAX #29.
_OTHER, _CONTROL, _EXTEND, _SPACING, _PREP = 0, 1, 2, 3, 4
_L, _V, _T, _LV, _LVT, _RI, _JOIN = 5, 6, 7, 8, 9, 10, 11


def _in_ranges(code: int, ranges: tuple) -> bool:
    return any(low <= code <= high for low, high in ranges)


def _is_ext_pict(code: int) -> bool:
    """True for Extended_Pictographic, which GB11 needs on both sides of a ZWJ."""
    return _in_ranges(code, _EXT_PICT_RANGES)


def _break_class(char: str) -> int:  # noqa: PLR0911, PLR0912 - one branch per UAX #29 class
    """Return the grapheme-cluster-break class of one character."""
    code = ord(char)
    if char == _ZWJ:
        return _JOIN
    if char in (_CR, _LF):
        return _CONTROL
    if code in _PREPEND:
        return _PREP
    if code in _TAGS or code in _OTHER_GRAPHEME_EXTEND or code in _SKIN_TONES:
        return _EXTEND
    if _in_ranges(code, _LAG_EXTEND):
        return _EXTEND
    if _in_ranges(code, _LAG_CONTROL):
        return _CONTROL
    if code in _REGIONAL_INDICATOR:
        return _RI

    category = unicodedata.category(char)
    if category in ("Mn", "Me"):
        return _EXTEND
    if category == "Mc":
        return _OTHER if code in _NOT_SPACING_MARK else _SPACING
    if code in _EXTRA_SPACING_MARK:
        return _SPACING
    if category in ("Cc", "Cf", "Zl", "Zp", "Cs"):
        return _CONTROL

    if code in _HANGUL_SYLLABLES:
        return _LV if (code - 0xAC00) % 28 == 0 else _LVT
    if _in_ranges(code, tuple((r.start, r.stop - 1) for r in _HANGUL_L)):
        return _L
    if _in_ranges(code, tuple((r.start, r.stop - 1) for r in _HANGUL_V)):
        return _V
    if _in_ranges(code, tuple((r.start, r.stop - 1) for r in _HANGUL_T)):
        return _T

    return _OTHER


#: Hangul jamo and syllables, which take the standard composition path.
_HANGUL_CLASSES = (_L, _V, _T, _LV, _LVT)

#: What an emoji run's lookback may cross on its way back to the pictograph.
#: UAX #29 GB11 says Extend* only; Elixir also crosses SpacingMark, verified
#: against 1.18.3 over every intervening class (Other, ZWJ, Prepend, Control
#: and a non-SpacingMark Mc all stop it).
_RUN_CONTINUES = (_EXTEND, _SPACING)


def _ext_pict_run_before(codes: list[int], classes: list[int], zwj_index: int) -> bool:
    """True if the ZWJ at `zwj_index` closes an `ExtPict (Extend | SpacingMark)*` run."""
    index = zwj_index - 1
    while index >= 0 and classes[index] in _RUN_CONTINUES:
        index -= 1
    return index >= 0 and classes[index] == _OTHER and _is_ext_pict(codes[index])


def _fallback_clusters(text: str) -> list[str]:  # noqa: PLR0912 - one branch per boundary rule
    """Split into grapheme clusters the way Elixir does.

    GB1-GB13, with two deliberate deviations from UAX #29 that copy Elixir:
    GB9c (the Unicode 15.1 Indic conjunct rule) is not implemented, and an
    emoji ZWJ run ends at the joiner unless a pictograph follows. Elixir is the
    authority here, not the spec -- see the comment above.
    """
    if not text:
        return []

    classes = [_break_class(char) for char in text]
    codes = [ord(char) for char in text]
    clusters = []
    start = 0
    ri_run = 0

    for index in range(1, len(text)):
        before, after = classes[index - 1], classes[index]

        if before == _RI:
            ri_run += 1
        else:
            ri_run = 0

        if text[index - 1] == _CR and text[index] == _LF:
            brk = False  # GB3
        elif _CONTROL in (before, after):
            brk = True  # GB4, GB5
        elif before == _JOIN and _ext_pict_run_before(codes, classes, index - 1):
            # GB11, as Elixir actually implements it. The spec would keep any
            # Extend attached across the joiner (GB9). Elixir instead ends the
            # emoji run at the joiner unless another pictograph follows, so
            # `©<ZWJ><combining acute>` is two graphemes to Elixir and one to
            # the spec. Verified against Elixir 1.18.3 by the lead/follower
            # sweep in `tools/unicode_parity/probe.exs`; the sizes are defined
            # there rather than quoted here, so they cannot drift out of date.
            brk = not _is_ext_pict(codes[index])
        elif before == _L and after in (_L, _V, _LV, _LVT):
            brk = False  # GB6
        elif before in (_LV, _V) and after in (_V, _T):
            brk = False  # GB7
        elif before in (_LVT, _T) and after == _T:
            brk = False  # GB8
        elif after in (_EXTEND, _JOIN):
            brk = False  # GB9
        elif after == _SPACING:
            brk = False  # GB9a
        elif before == _PREP:
            brk = False  # GB9b
        elif before == _RI and after == _RI and ri_run % 2 == 1:
            brk = False  # GB12, GB13
        else:
            brk = True  # GB999

        if brk:
            clusters.append(text[start:index])
            start = index

    clusters.append(text[start:])
    return clusters


def grapheme_clusters(text: str) -> list[str]:
    """Split `text` into user-perceived characters, the way Elixir would."""
    if not text:
        return []
    return _fallback_clusters(text)


def grapheme_length(text: str) -> int:
    """Count user-perceived characters, the way Ecto's `validate_length` does."""
    return len(grapheme_clusters(text))


def truncate_graphemes(text: str, limit: int) -> str:
    """Cut `text` to `limit` graphemes without splitting one in half."""
    clusters = grapheme_clusters(text)
    if len(clusters) <= limit:
        return text
    return "".join(clusters[:limit])


# Normalisation. `sanitize_name` normalises on every pass and step lookup
# matches names as text, so Apollo and Lightning have to agree on the normal
# form or a lookup for an accented name silently misses.

#: Canonical combining class for codepoints Python's `unicodedata` does not
#: know yet. Break class and ccc are independent properties, so the codepoint
#: sweep that found `_LAG_EXTEND` could not see this: these ten already had
#: their break class corrected there, and their ccc rode along wrong.
#: Regenerate with tools/unicode_parity/probe.exs (see ccc).
_LAG_CCC = {
    0x10EFD: 220, 0x10EFE: 220, 0x10EFF: 220,
    0x11F41: 9, 0x11F42: 9,
    0x1E08F: 230,
    0x1E4EC: 232, 0x1E4ED: 232, 0x1E4EE: 220, 0x1E4EF: 230,
}


def _combining_class(char: str) -> int:
    """Canonical combining class, with the codepoints Python does not know yet."""
    return _LAG_CCC.get(ord(char)) or unicodedata.combining(char)


def _canonical_order(text: str) -> str:
    """Reorder combining marks by combining class, for the codepoints Python misses.

    `unicodedata.normalize` reads a ccc of 0 for anything it thinks is
    unassigned, so it leaves those marks where they are instead of sorting them
    into the run. This corrective pass sorts each run of non-starters with the
    merged table.
    """
    chars = list(text)
    start = None
    for index in range(len(chars) + 1):
        ccc = _combining_class(chars[index]) if index < len(chars) else 0
        if ccc == 0:
            if start is not None and index - start > 1:
                chars[start:index] = sorted(chars[start:index], key=_combining_class)
            start = None
        elif start is None:
            start = index
    return "".join(chars)


def _compose_pair(first: str, second: str) -> str | None:
    """Return the single character `first` + `second` compose to, or None."""
    composed = unicodedata.normalize("NFC", first + second)
    return composed if len(composed) == 1 else None


def _compose(text: str) -> str:
    """Canonical composition the way OTP does it, which is not the way the spec does.

    The spec composes a mark onto the nearest preceding starter unless
    something between them blocks it (an intervening character whose combining
    class is greater than or equal to the mark's). OTP does neither half of
    that: it composes onto the *grapheme cluster's leading character* and
    ignores blocking entirely.

    So `"e" + VS16 + acute` is three characters to the spec -- VS16 has a
    combining class of 0 and blocks the acute -- and `"é" + VS16` to OTP. ICU
    and Python agree with the spec, which makes OTP the deviant one, and this
    function copies it anyway: Lightning normalises with Elixir, and step
    lookup matches names as text, so a name Apollo normalises differently is a
    name Apollo cannot find.

    Measured over the parity corpus, the difference is not exotic: it reaches
    Bengali, Tamil, Malayalam, Sinhala, Oriya, Telugu, Kannada, Balinese,
    Chakma and Grantha two-part vowels, Thai and Lao SARA AM, and any base
    followed by one of the combining-class-zero Extend characters -- every
    variation selector, every skin-tone modifier, and U+034F.
    """
    composed = []
    for cluster in grapheme_clusters(text):
        if any(_break_class(char) in _HANGUL_CLASSES for char in cluster):
            # Hangul takes the standard-library path because the rule below is
            # actively wrong here: jamo have a combining class of zero, so
            # "reach back to the cluster lead" reaches straight past an
            # intervening jamo, and `ᄀ까` (U+1100 U+AE4C) came out as `가ᄁ` —
            # a Korean step name rewritten into a different one.
            #
            # This is a partial fix, not a correct one. OTP does not agree with
            # the standard library here: it composes onto the cluster lead, so
            # it decomposes a precomposed syllable that is not the lead, and
            # `U+1113 U+AC00` is `1113,1100,1161` in OTP against `1113,AC00`
            # here. Routing to the standard library trades one divergence for
            # another, and the trade is not small: 17,422 unique signatures
            # of the parity corpus are pinned as a result.
            #
            # FOUR mechanisms are involved, not one, and they do not all point
            # the same way — a fix aimed at the obvious case (a jamo lead
            # before a precomposed syllable) makes another of them worse,
            # because they are opposite directions. Read the group 2 notes in
            # `tools/unicode_parity/known_nfc_divergences.txt` before changing
            # anything here. Settling it is OpenFn/apollo#655, which gates
            # APOLLO_UNICODE_STEP_NAMES.
            #
            # Do not read the pinned counts as the size of the gap: they are
            # the size of its intersection with that corpus. Measured
            # exhaustively rather than over the probe, the composition-rule
            # group alone is 91,200 against the 32 the probe finds. The
            # divergence in the largest group is 106 of 125 jamo leads (84.8%).
            #
            # Ordinary Korean text round-trips — `한국어`, `안녕하세요`,
            # `환자 등록` — but one of the four mechanisms (OTP deleting
            # U+11A7 after an LV syllable) is PURE Hangul, so "the divergence
            # is cross-script" is wrong and earlier revisions of this comment
            # said it.
            composed.append(unicodedata.normalize("NFC", cluster))
            continue

        lead, trailing = cluster[0], []
        previous_ccc = None
        for char in cluster[1:]:
            ccc = _combining_class(char)
            # Standard blocking — a character composes unless the one before it
            # has an equal or higher combining class — but measured against the
            # *cluster's lead*, which never moves. The spec instead re-bases on
            # every character of class zero it passes, and that is the whole
            # difference: OTP keeps reaching back to the lead, so a mark can be
            # pulled forward past several class-zero characters to compose with
            # it. `"e" + VS16 + acute` is `"é" + VS16` here and three separate
            # characters under the spec.
            if previous_ccc is None or previous_ccc == 0 or previous_ccc < ccc:
                merged = _compose_pair(lead, char)
                if merged is not None:
                    lead = merged
                    continue
            trailing.append(char)
            previous_ccc = ccc
        composed.append(lead)
        composed.extend(trailing)
    return "".join(composed)


def normalize_nfc(text: str) -> str:
    """NFC as Elixir performs it, which is what Lightning stores.

    Two deliberate departures from `unicodedata.normalize("NFC", ...)`, both to
    match Elixir: the combining classes Python's tables predate (`_LAG_CCC`),
    and OTP's composition rule (`_compose`).

    KNOWN GAPS, in two unrelated mechanisms. Both are enumerated row by row in
    ``tools/unicode_parity/known_nfc_divergences.txt``; `check.py` asserts that
    file's row count against what it measures, so the figures are re-derivable
    from the tree rather than quoted here from a corpus that may not survive
    the next rebuild. Run ``elixir probe.exs`` then ``python3 check.py``.

    The first is this function's composition rule, described below. The second
    is the Hangul routing in `_compose`, which is much the larger of the two
    and which gates APOLLO_UNICODE_STEP_NAMES — see the comment there and
    OpenFn/apollo#655. Neither is fixed; both are pinned.

    The composition gap is one shape: combining classes ``(0, 230, 0, 220)`` —
    a base, a mark, any class-zero character, then a mark of *lower* class. The
    minimal case is four codepoints::

        A U+0302 U+200C U+0323
        Elixir  ->  U+00C2 U+200C U+0323   (composes the first mark only)
        here    ->  U+1EAC U+200C          (composes both)

    ZWNJ is routine in Persian and Indic text, so this is reachable, not
    exotic. Eight structurally different blocking rules were fitted against the
    corpora and none reaches zero: the shapes conflict, because the same corpus
    that requires composition to reach past a class-zero character also
    contains cases that require it not to. Do not "fix" this by guessing —
    extend the probe and fit against its output.

    ACCEPTED, with the bound stated rather than hand-waved. What this costs is
    a step lookup missing when a name in this shape reaches lookup without
    being sanitized first. It is not bounded by "sanitized names are fixed
    points" or by "no Lightning-valid name is altered" — both of those claims
    appeared here and both were false. `sanitize_name` output *is* a fixed
    point for every case the harness covers, which is evidence and not a proof.
    """
    if not text:
        return text
    return _compose(_canonical_order(unicodedata.normalize("NFD", text)))


def sanitize_name(name: str, unicode_mode: bool | None = None) -> str:
    """Return `name` with every character the active rule forbids removed.

    Under the ASCII rule, letters are folded to their nearest ASCII form first
    (``Café`` -> ``Cafe``) so accented names degrade into something readable
    rather than losing whole words, and anything still not ASCII is dropped.
    Under the permissive rule nothing is folded and nothing is dropped except
    the rejected set -- the name is kept exactly as typed.

    In both modes: forbidden whitespace becomes a plain space, the result is
    trimmed with exactly the set Elixir's `String.trim/1` strips, then
    NFC-normalised, then capped at MAX_NAME_LENGTH graphemes without ever
    cutting a grapheme in half. The result is a fixed point.
    """
    if not name or not isinstance(name, str):
        return name
    if unicode_mode is None:
        unicode_mode = unicode_names_enabled()

    text = normalize_nfc(name)

    # Forbidden-but-whitespace characters become a plain space here, before the
    # ASCII fold rather than after it. A tab, a newline or a U+2028 is rejected
    # either way, but the useful reading of it in a name is "a space", and doing
    # it up front means both modes agree -- the fold would otherwise drop the
    # non-ASCII ones outright and silently join the words either side.
    text = "".join(" " if _is_forbidden(c) and c.isspace() else c for c in text)

    if not unicode_mode:
        # Fold diacritics onto their base letters, then drop whatever is left
        # that is not ASCII. This is the long-standing behaviour, plus a table
        # for the handful of letters NFKD cannot decompose at all. NFKD also
        # turns the exotic spaces (NBSP, ideographic space) into plain ones.
        text = text.translate(_ASCII_TRANSLITERATIONS)
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    kept = []
    for char in text:
        if _is_forbidden(char):
            continue
        if unicode_mode or char in _ASCII_ALLOWED:
            kept.append(char)

    # Trim before normalising, not after. Trimming can uncover a combining mark
    # that only composes once the character in front of it is gone, and
    # truncating can uncover the same boundary again, so repeat until it
    # settles. is_valid_name asks whether a name equals this function's output,
    # so that output has to be a fixed point or a sanitised name reads as
    # invalid.
    text = "".join(kept)
    for _ in range(_SANITIZE_PASSES):
        settled = text
        text = normalize_nfc(text.strip(_TRIM_CHARS))
        text = truncate_graphemes(text, MAX_NAME_LENGTH).strip(_TRIM_CHARS)
        if text == settled:
            return text

    raise RuntimeError(
        f"sanitize_name did not settle in {_SANITIZE_PASSES} passes. Two are "
        "enough for every input tested, so reaching this means an assumption "
        "in normalize_nfc or truncate_graphemes has moved. Returning here "
        "would hand back a name that is_valid_name then calls invalid."
    )


def is_valid_name(name: str, unicode_mode: bool | None = None) -> bool:
    """Return True if `name` already satisfies the active rule (sanitising is a no-op)."""
    if not isinstance(name, str):
        return False
    return sanitize_name(name, unicode_mode) == name


def first_invalid_char(name: str, unicode_mode: bool | None = None) -> str | None:
    """Return the first character of `name` the active rule forbids, or None."""
    if unicode_mode is None:
        unicode_mode = unicode_names_enabled()
    for char in name:
        if not is_allowed_char(char, unicode_mode):
            return char
    return None


def describe_rule(unicode_mode: bool | None = None) -> str:
    """One sentence stating the active rule, for the workflow-generation prompt.

    The prompt and the sanitiser must describe the same rule. Building the
    prompt text from here means there is only one place to change when the
    rule changes.
    """
    if unicode_mode is None:
        unicode_mode = unicode_names_enabled()
    if unicode_mode:
        return (
            "Job names may contain anything except control characters. Letters and marks from any "
            "script, punctuation, symbols and emoji are all fine, so `Vérifier l'état`, `患者確認`, "
            "`Проверка данных` and `Import A/B` are all valid names. Write the name the user asked "
            "for, as they wrote it — do not strip accents or transliterate."
        )
    return (
        "Job names may use only unaccented English letters, digits, spaces, hyphens and underscores. "
        "Write accented or non-Latin names in that form instead (`Vérifier l'état` becomes "
        "`Verifier letat`)."
    )


def describe_rule_for_prompt(unicode_mode: bool | None = None) -> str:
    """The full job-naming bullet used in the workflow-generation prompt."""
    return (
        f"{describe_rule(unicode_mode)} Names must be at most {MAX_NAME_LENGTH} characters "
        "and must be unique within a workflow."
    )


def describe_rule_for_judge(unicode_mode: bool | None = None) -> str:
    """The naming rule as a grading instruction, for the acceptance-test judges.

    The judges are LLM prompts that grade generated workflows. They used to
    restate the rule as static prose, which meant a third copy that could not
    follow the flag: with the ASCII rule active they would have passed a name
    the sanitizer was in fact folding. `judges.load_judge` substitutes this in.
    """
    if unicode_mode is None:
        unicode_mode = unicode_names_enabled()
    if unicode_mode:
        common = (
            "Job names, job keys, trigger keys and edge `source_*`/`target_*` references must "
            "contain no control characters. Nothing else about their characters is a defect: "
            "accented Latin (`Vérifier l'état`), non-Latin (`患者確認`, `Проверка данных`), "
            "punctuation, symbols and emoji are all valid. Do not flag a name for being "
            "non-English, accented, or containing punctuation."
        )
    else:
        common = (
            "Job names, job keys, trigger keys and edge `source_*`/`target_*` references must use "
            "only unaccented English letters, digits, spaces, hyphens and underscores. Flag "
            "anything else: an accented or non-Latin name that reached the output means the "
            "service failed to fold it."
        )
    return (
        f"{common} Job names must be unique within a workflow and at most "
        f"{MAX_NAME_LENGTH} characters."
    )


def normalize_for_lookup(name: str) -> str:
    """Fold a name into the key used to match it against a job key or job name.

    Case-folded, NFC-normalised, and every character that is not a letter, mark
    or digit replaced with a hyphen. Unicode-aware in both modes: the old
    ASCII-only version folded every non-Latin name to the empty string, so any
    non-Latin lookup matched the first non-Latin job in the workflow.

    Case folding rather than lowercasing, so that the pairs `.lower()` leaves
    distinct still match: Greek final sigma against medial sigma, and German
    ss against sz.

    Callers must treat an empty result as "no fuzzy match available" rather
    than as a key -- see ``yaml_utils.find_job_in_yaml``.
    """
    if not isinstance(name, str):
        return ""
    text = normalize_nfc(name).casefold()
    folded = "".join(
        char if unicodedata.category(char)[0] in _LETTER_MARK_DIGIT else "-" for char in text
    )
    return folded.strip("-")
