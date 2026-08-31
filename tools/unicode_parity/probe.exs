# Ground truth for services/name_rules.py, generated from the Elixir that
# Lightning actually runs.
#
# Apollo caps step names at 100 graphemes because Ecto's `validate_length`
# counts graphemes, so Apollo's clustering has to agree with Elixir's
# `String.length/1`. Elixir deviates from UAX #29 in two known places, so the
# target is Elixir's behaviour, not the spec, and the only honest way to get it
# is to ask Elixir.
#
# Usage, from this directory, with the Elixir version Lightning runs:
#
#     elixir probe.exs            # writes the data files below
#     python3 check.py            # compares, and prints tables to paste back
#
# Outputs (all under ./out):
#   classmap.txt   every codepoint's grapheme-break bucket
#   extpict.txt    the Extended_Pictographic set
#   trim.txt       what String.trim/1 strips
#   lookback.txt   what a GB11 emoji run may be separated from its ZWJ by
#   ccc.txt        canonical combining class, for NFC parity
#   nfc_strings.txt     whole strings, with OTP's NFC of each
#   clusters.txt        the same strings, split into graphemes
#   version.txt    the Elixir and OTP versions these came from
#
# Run `python3 edges.py` FIRST: it writes out/range_edges.txt from the range
# tables in name_rules, and this probe crosses those edges into its shapes.
#
# Re-run whenever Elixir's or Python's Unicode version moves.

File.mkdir_p!("out")

zwj = <<0x200D::utf8>>
emoji = <<0x1F600::utf8>>
acute = <<0x301::utf8>>

codepoints = Enum.reject(0..0x10FFFF, &(&1 >= 0xD800 and &1 <= 0xDFFF))

hex = fn cp -> Integer.to_string(cp, 16) end

# --- 1. break-class buckets ---------------------------------------------------
# A = attaches to what precedes it, P = prepends to what follows,
# C = control (breaks on both sides), O = anything else (not emitted).
bucket = fn cp ->
  s = <<cp::utf8>>

  cond do
    String.length("a" <> s) == 1 -> "A"
    String.length(s <> "a") == 1 -> "P"
    String.length(s <> acute) == 2 -> "C"
    true -> "O"
  end
end

classmap =
  codepoints
  |> Enum.map(&{&1, bucket.(&1)})
  |> Enum.reject(fn {_, b} -> b == "O" end)
  |> Enum.map_join("\n", fn {cp, b} -> "#{hex.(cp)} #{b}" end)

File.write!("out/classmap.txt", classmap <> "\n")

# --- 2. Extended_Pictographic -------------------------------------------------
# ExtPict is NOT a break class, so the bucket sweep above cannot see it and an
# over-broad set here is invisible to that check. Probe it through GB11 instead:
# `cp ZWJ emoji` collapses to one grapheme only when cp is pictographic.
lead = Enum.filter(codepoints, &(String.length(<<&1::utf8>> <> zwj <> emoji) == 1))
follow = Enum.filter(codepoints, &(String.length(emoji <> zwj <> <<&1::utf8>>) == 1))

if lead != follow do
  IO.puts(:stderr, "WARNING: the two ExtPict probe directions disagree")
end

File.write!("out/extpict.txt", Enum.map_join(lead, "\n", hex) <> "\n")

# --- 3. String.trim/1 ---------------------------------------------------------
trimmed = Enum.filter(codepoints, &(String.trim(<<&1::utf8>> <> "x") == "x"))
File.write!("out/trim.txt", Enum.map_join(trimmed, "\n", hex) <> "\n")

# --- 4. GB11 lookback ---------------------------------------------------------
# Which single intervening character an emoji run survives, between the
# pictograph and the ZWJ. UAX #29 says Extend only; Elixir also allows
# SpacingMark.
lookback =
  codepoints
  |> Enum.filter(&(String.length(<<0x2764::utf8>> <> <<&1::utf8>> <> zwj <> emoji) == 1))
  |> Enum.map_join("\n", hex)

File.write!("out/lookback.txt", lookback <> "\n")

# --- 5. normalisation --------------------------------------------------------
# `sanitize_name` normalises to NFC twice and stakes step-lookup identity on
# Apollo and Lightning agreeing on the normal form. Nothing above can see that:
# the canonical combining class is not a break class, so a codepoint can have
# the right break class and still normalise differently. Emit every codepoint
# whose ccc is non-zero, plus every one whose NFC form differs from itself.
ccc =
  codepoints
  |> Enum.map(fn cp ->
    {cp, :unicode_util.lookup(cp)[:ccc] || 0}
  end)
  |> Enum.reject(fn {_, c} -> c == 0 end)
  |> Enum.map_join("\n", fn {cp, c} -> "#{hex.(cp)} #{c}" end)

File.write!("out/ccc.txt", ccc <> "\n")

# Per-codepoint checks cannot see the composition rule at all: OTP's NFC
# deviates from the spec only at three characters or more, so a whole-string
# comparison is the only thing that can catch it.
#
# The shapes are built explicitly rather than sampled from a flat pool. A
# uniform pool is almost all filler — precomposed Hangul and CJK that
# normalise trivially — and the shapes that actually discriminate this
# implementation from the standard library turn up at about 1e-6, so a mutant
# restoring a known bug survives. Each block below is a shape that is known to
# separate them, or a shape a name can realistically contain.

bases = [0x41, 0x61, 0x4F, 0x45, 0x55, 0x0995, 0x0B95, 0x0D15, 0x0D9A, 0x0C95, 0x0E01, 0x0915]
marks = [0x0300, 0x0301, 0x0302, 0x0303, 0x0308, 0x030C, 0x0327, 0x0323, 0x0331, 0x0316, 0x0345]
zero_extend = [0x200C, 0x200D, 0xFE00, 0xFE0F, 0x034F, 0x1F3FB, 0x1F3FF, 0xE0067]
two_part_vowels = [
  [0x0995, 0x09C7, 0x09BE], [0x0B95, 0x0BC6, 0x0BBE], [0x0D15, 0x0D46, 0x0D3E],
  [0x0D9A, 0x0DD9, 0x0DCF], [0x0C95, 0x0CC6, 0x0CC2], [0x0B15, 0x0B47, 0x0B3E],
  [0x11103, 0x11127, 0x1112C]
]
prepends = [0x0600, 0x06DD, 0x0890, 0x0D4E, 0x11A3A, 0x11D46, 0x11F02]

# Hangul syllables split by whether they carry a trailing consonant: an LV
# syllable decomposes to two jamo and an LVT to three, and the two behave
# differently under a rule that composes onto the cluster lead.
lv_syllables = Enum.take_every(for(s <- 0xAC00..0xD7A3, rem(s - 0xAC00, 28) == 0, do: s), 4)
lvt_syllables = Enum.take_every(for(s <- 0xAC00..0xD7A3, rem(s - 0xAC00, 28) != 0, do: s), 105)

# What follows the pair. "Nothing" was the only case the corpus had.
# U+11A7 is deliberately included: it sits one below the trailing-consonant
# range and OTP deletes it after an LV syllable or an L+V pair. Starting the
# trailers at U+11A8 made that mechanism invisible.
trailers = [[], [0x61], [0x0301], [0x11A7], [0x11A8], [0x11FF], [0x1161], [0xAC00], [0x0020, 0x62]]

two_part_vowel_marks = [0x0CC0, 0x09CB, 0x0BCA, 0x0D4A, 0x0DDC, 0x1B40, 0x0CC7, 0x0D4C]

# Written by edges.py from the range tables in `services/name_rules.py`, so a
# range added there is swept here without anyone remembering to.
range_edges =
  case File.read("out/range_edges.txt") do
    {:ok, text} ->
      text |> String.split("\n", trim: true) |> Enum.map(&String.to_integer(&1, 16))

    {:error, _} ->
      raise "out/range_edges.txt is missing. Run `python3 edges.py` before probe.exs."
  end
regional = [0x1F1E6, 0x1F1EB, 0x1F1F7, 0x1F1FF]
pictographs = [0x00A9, 0x2764, 0x1F469, 0x1F4BB, 0x1F3F4]
ascii_words = [~c"Fetch Data", ~c"step-1", ~c"a_b c", ~c"Verifier letat"]
lag_ccc = [0x10EFD, 0x11F41, 0x1E08F, 0x1E4EC, 0x1E4EE]

shapes =
  # base + mark + class-zero Extend + mark: the shape OTP and the spec differ
  # on, swept exhaustively rather than sampled.
  (for b <- bases, m1 <- marks, z <- zero_extend, m2 <- marks, do: [b, m1, z, m2]) ++
  (for b <- bases, z <- zero_extend, m1 <- marks, m2 <- marks, do: [b, z, m1, m2]) ++
  # base + two marks, no separator: canonical ordering with no divergence
  (for b <- bases, m1 <- marks, m2 <- marks, do: [b, m1, m2]) ++
  # the two-part vowels, alone and with a mark or a separator after
  (for [b, v1, v2] <- two_part_vowels,
       tail <- [[], [0x0301], [0x200C], [0x200C, 0x0301]],
       do: [b, v1, v2] ++ tail) ++
  # The two halves of a two-part vowel SEPARATED by a class-zero character.
  # This is the shape the `previous_ccc == 0` clause in `_compose` exists for,
  # and the corpus did not contain it — so deleting that clause left the
  # harness green. Every mutation that survives points at a missing shape.
  (for [_b, v1, v2] <- two_part_vowels, z <- zero_extend, do: [v1, z, v2]) ++
  (for [b, v1, v2] <- two_part_vowels, z <- zero_extend, do: [b, v1, z, v2]) ++
  (for [b, v1, v2] <- two_part_vowels, z <- zero_extend, m <- [0x0301, 0x0323],
       do: [b, v1, z, v2, m]) ++
  # SARA AM, which decomposes
  (for b <- [0x0E01, 0x0EA1], v <- [0x0E33, 0x0EB3], tail <- [[], [0x0301], [0x200C]],
       do: [b, v] ++ tail) ++
  # the codepoints whose combining class Python's tables predate
  (for b <- bases, l <- lag_ccc, m <- marks, do: [b, l, m]) ++
  (for b <- bases, m <- marks, l <- lag_ccc, do: [b, m, l]) ++
  # Prepend, regional indicators and ZWJ sequences, with marks attached
  (for p <- prepends, b <- bases, m <- marks, do: [p, b, m]) ++
  (for a <- regional, b <- regional, m <- marks, do: [a, b, m]) ++
  (for a <- pictographs, b <- pictographs, m <- marks, do: [a, 0x200D, b, m]) ++
  # Hangul: L + precomposed syllable, and L L V adjacency. Jamo have a
  # combining class of zero, so a composition rule that reaches back past a
  # class-zero character rewrites Korean names into different ones. The corpus
  # had no Hangul at all and could not see it.
  # Sampling four syllables here is how a 29,893-row gap read as 949. LV
  # (no trailing consonant) and LVT (with one) decompose to different lengths,
  # and what follows the pair matters too, so all three axes are swept rather
  # than sampled on one and fixed on the others.
  (for l <- 0x1100..0x115F, sy <- lv_syllables, do: [l, sy]) ++
  (for l <- 0x1100..0x115F, sy <- lvt_syllables, do: [l, sy]) ++
  (for l <- 0x1100..0x1112, sy <- Enum.take_every(lv_syllables, 2), t <- trailers, do: [l, sy | t]) ++
  (for l <- 0x1100..0x1112, sy <- Enum.take_every(lvt_syllables, 2), t <- trailers, do: [l, sy | t]) ++
  # The boundary of every range in `name_rules`, plus one either side, read
  # from out/range_edges.txt (written by edges.py). A hand-picked slice of a
  # range never steps across its edge, and three rounds running that is exactly
  # where the surviving mutant was — U+1160 HANGUL JUNGSEONG FILLER is assigned
  # and GCB=V, and the sweep started at U+1161.
  (for e <- range_edges, do: [e]) ++
  (for e <- range_edges, v <- [0x1161, 0x0301, 0x61], do: [e, v]) ++
  (for e <- range_edges, l <- [0x1100, 0xAC00], do: [l, e]) ++
  (for e <- range_edges, do: [0x1100, e, 0x11A8]) ++
  # Extended jamo: U+A960-A97C (L), U+D7B0-D7C6 (V), U+D7CB-D7FB (T). The
  # corpus contained zero codepoints from all three, so narrowing any of the
  # three `_HANGUL_*` ranges in `name_rules` left the harness at exit 0 while
  # `U+A960 U+1161` went from one grapheme to two.
  (for l <- 0xA960..0xA97C, v <- 0x1161..0x1165, do: [l, v]) ++
  (for l <- 0x1100..0x1105, v <- 0xD7B0..0xD7C6, do: [l, v]) ++
  (for l <- 0x1100..0x1105, v <- 0x1161..0x1163, t <- 0xD7CB..0xD7FB, do: [l, v, t]) ++
  (for l <- 0xA960..0xA97C, v <- 0xD7B0..0xD7B4, t <- [0x11A8, 0xD7CB], do: [l, v, t]) ++
  (for a <- 0x1100..0x1105, b <- 0x1100..0x1105, v <- 0x1161..0x1165, do: [a, b, v]) ++
  (for l <- 0x1100..0x1105, v <- 0x1161..0x1165, t <- 0x11A7..0x11AC, do: [l, v, t]) ++
  # Syllable-block edges, which a stride steps over.
  (for l <- 0x1100..0x1112, sy <- [0xAC00, 0xAC01, 0xD7A2, 0xD7A3], t <- trailers, do: [l, sy | t]) ++
  (for v <- 0x1161..0x1175, t <- [0x11A7, 0x11A8], do: [0x1100, v, t]) ++
  (for l <- 0x1100..0x115F, v <- two_part_vowel_marks, do: [l, v]) ++
  (for l <- 0x1100..0x1112, v <- two_part_vowel_marks, t <- trailers, do: [l, v | t]) ++
  # Hangul crossed with Prepend, which the sweep never covered: OTP
  # decomposes a precomposed syllable that is not the cluster lead.
  (for p <- prepends, sy <- [0xAC00, 0xAE4C, 0xD55C], do: [p, sy]) ++
  (for p <- prepends, l <- 0x1100..0x1105, v <- 0x1161..0x1163, do: [p, l, v]) ++
  # CR and LF, for GB3/GB4/GB5. The corpus had neither.
  (for a <- [0x0D, 0x0A], b <- [0x0D, 0x0A, 0x61], do: [a, b]) ++
  (for b <- bases, do: [b, 0x0D, 0x0A, b]) ++
  # Odd-length regional indicator runs, for the GB12/GB13 parity rule. The
  # corpus only had pairs, which an implementation with no parity rule also
  # gets right.
  (for n <- 1..5, do: List.duplicate(0x1F1EB, n)) ++
  (for n <- 1..5, do: List.duplicate(0x1F1EB, n) ++ [0x0301]) ++
  (for a <- regional, b <- regional, c <- regional, do: [a, b, c]) ++
  # The two places Elixir deviates from UAX #29, which the corpus previously
  # lacked entirely. `regex` undercounts on both — 100 where Elixir says 200 —
  # so without these the corpus shows only the direction that truncates early
  # and hides the direction that ships a name over the cap.
  (for p <- pictographs, m <- marks, n <- [1, 3, 50], do: List.duplicate([p, 0x200D, m], n) |> List.flatten()) ++
  (for c1 <- [0x0915, 0x0937, 0x0924], c2 <- [0x0915, 0x0937, 0x0924], n <- [1, 3],
       do: List.duplicate([c1, 0x094D, c2], n) |> List.flatten()) ++
  [[0x0928, 0x092E, 0x0938, 0x094D, 0x0924, 0x0947]] ++
  # pure ASCII, which must be untouched
  Enum.map(ascii_words, & &1) ++
  (for w <- ascii_words, m <- marks, do: w ++ [m])

nfc_pairs =
  Enum.map_join(shapes, "\n", fn cps ->
    input = List.to_string(cps)
    output = :unicode.characters_to_nfc_binary(input)

    Enum.map_join(cps, ",", hex) <>
      "\t" <> Enum.map_join(:unicode.characters_to_list(output), ",", hex)
  end)

File.write!("out/nfc_strings.txt", nfc_pairs <> "\n")

# Cluster boundaries for the same corpus. `check.py` compared six things and
# not one of them was a cluster boundary — the clusterer was checked only
# through per-codepoint break classes, which cannot see the regional-indicator
# parity rule or the CR-LF rule at all.
clusters =
  Enum.map_join(shapes, "\n", fn cps ->
    input = List.to_string(cps)

    boundaries =
      input
      |> String.graphemes()
      |> Enum.map_join(",", fn g ->
        g |> :unicode.characters_to_list() |> Enum.map_join("+", &Integer.to_string(&1, 16))
      end)

    Enum.map_join(cps, ",", hex) <> "\t" <> boundaries
  end)

File.write!("out/clusters.txt", clusters <> "\n")

IO.puts("nfc corpus rows: #{length(shapes)}")

File.write!(
  "out/version.txt",
  "elixir #{System.version()}\notp #{System.otp_release()}\n"
)

IO.puts("wrote out/{classmap,extpict,trim,lookback,ccc,nfc_strings,clusters,version}.txt")
