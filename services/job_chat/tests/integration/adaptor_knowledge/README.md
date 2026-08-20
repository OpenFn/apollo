# Adaptor knowledge probes

A 30-case benchmark for **how well job_chat can answer questions whose answer
lives in an adaptor's documentation**. Each case asks a question with exactly
one documented right answer, then checks the reply with a regex. The run prints
a per-group score.

Use it to:

- **Measure a new retrieval method.** Score before, change the pipeline, score
  after. The groups tell you which part of the docs surface your method reached.
- **Catch regressions.** Anything that changes prompt construction, doc ingest,
  or model version can quietly cost adaptor accuracy. Nothing else in the repo
  would notice.

Many cases fail on the current pipeline. That's deliberate — a benchmark that
starts green has no room to measure an improvement.

## Before you run: check the docs pipeline

job_chat loads an adaptor's docs by calling the `adaptor_apis` service over HTTP
on port 3000, which fetches adaptor source from the GitHub contents API. If that
chain is broken the prompt degrades *silently* — no error, just a generic
"The user is using an OpenFn Adaptor" line — and every case fails for a reason
that has nothing to do with retrieval.

So: start the server, then preflight it.

```bash
bun start
```

```bash
curl -s -X POST http://127.0.0.1:3000/services/adaptor_apis -H 'Content-Type: application/json' -d '{"adaptors":["@openfn/language-gmail@3.2.0"]}'
```

You want `errors: []` and a non-empty `docs`. If you get
`{"docs":{},"errors":[...]}`, note that **the reason is not in that response** —
it's discarded before it reaches any caller, and only printed to the server's
own console. Go read the terminal running `bun start`.

Don't hand-populate `adaptor_function_docs` to get past a failing preflight.
Rows from anywhere but the real pipeline make the score unreadable: you can no
longer tell whether a change moved retrieval or just moved the fixture.

## Running

```bash
poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s
```

One group at a time:

```bash
poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s -k namespaces
```

`-s` is required — the scoreboard prints on stdout. Each case is one live
Anthropic call, so a full run costs 30.

These carry the `integration` marker (from the directory name) and live outside
`acceptance/`, so a normal acceptance run never collects them.

## Reading the score

The groups are not arbitrary. Each one names a **distinct capability** a
retrieval method has to have, and the doc surface it has to reach:

| Group | n | What passing it proves | Where that lives |
|---|---|---|---|
| `signatures` | 3 | Control. The function list job_chat already injects. | already in the prompt |
| `functions` | 6 | You retrieve parameter *semantics* — order, meaning, examples — not just the signature line | `## Functions` bodies |
| `interfaces` | 7 | You retrieve option-object property names | `## Interfaces` `@typedef`s |
| `namespaces` | 6 | You preserve the namespace prefix (`tracker.*`, `bulk2.*`, `util.*`, `http.*`) | `## <namespace>` |
| `other` | 3 | You reach beyond the API docs page | `configuration-schema`, README |
| `version` | 5 | You retrieve for the *pinned* version, not the latest | per-version docs |

**`signatures` is a smoke test, not a score.** If those three fail, job_chat
isn't getting an adaptor block at all — fix the prerequisites above and rerun.
No other number in that run means anything.

**The `version` group catches the obvious shortcut.** Four of its five cases are
deliberate inverses of a case in another group: identical prompt, different
pinned version, opposite correct answer.

| Latest-version case | Old-version inverse |
|---|---|
| `fn.http-post-data-positional` (7.3.2, `post(path, data)`) | `ver.http6-post-body-option` (6.5.4, `{body: ...}`) |
| `ns.dhis2-util-findattributevalue` (8.2.1, `util.` prefix) | `ver.dhis2-6-findattributevalue-toplevel` (6.3.4, no prefix) |
| `ns.salesforce-bulk2-insert` (9.1.5, `bulk2.insert`) | `ver.salesforce4-bulk-toplevel` (4.8.6, `bulk()`) |

A method that indexes only the latest docs passes one side of each pair and
fails the other, so its total barely moves while it has clearly got worse for
anyone pinned to an older adaptor. Watch the pairs, not just the total.

**Noise.** The model is stochastic and borderline cases flip between identical
runs. Treat a one- or two-point move as noise; run three times and compare
per-group rates before believing a change helped.

## Where the information is lost today

A starting map for anyone about to rewrite this. All three are in the current
pipeline, and each maps to a group above:

1. **Only the `signature` column is injected.** `prompt.py:generate_system_message`
   reads `signature` and ignores `function_data`, which already holds
   descriptions, params and examples. → `functions`
2. **`@typedef` doclets are dropped at ingest.** `load_adaptor_docs.filter_function_docs`
   discards them, so option-object properties like `SendMessageOptions.body`
   never reach the database at all. → `interfaces`
3. **The namespace prefix isn't in the signature.** It's in `function_name`
   (`bulk1.insert`) but not in `signature` (`insert(...)`), and only the
   signature is injected — so three different `insert(...)` lines appear
   identical, and `http.get` reads as a top-level `get`. → `namespaces`

`other` fails for a fourth reason: `configuration-schema` and the README are
never fetched by anything.

## Adding or tuning a case

Append a `Case` to the right list in `cases.py`.

- `expect` — passes if **any** pattern matches. Case-insensitive.
- `forbid` — fails if **any** pattern matches. Case-**sensitive**, because these
  name specific wrong identifiers and `fileName` must not match `filename`.
- `doc_ref` — the exact doc section the answer comes from.
- `why` — the wrong answer you expect. Prints on failure, which is what makes a
  red run a worklist instead of just red.
- `target` — keep `"code"` for anything asking for code, so prose *discussing* a
  wrong key ("you might reach for `text:`, but…") can't trip a `forbid`.

Assert the documented fact, not a style preference. A case that fails valid-but-
unfashionable code is a false signal that will mislead whoever reads the score.

If a probe needs real judgement rather than a string match, it belongs in
`../../acceptance/` as a markdown spec instead.

## Known limits of this suite

- The regexes approximate correctness. They have been checked against a right
  and a wrong answer each, but a novel phrasing can still fool one — audit
  passes as well as failures before trusting a big jump.
- No baseline is recorded here. The numbers measured during development came
  from hand-built fixture rows and did not describe the real service, so they
  were removed rather than left to be trusted. Establish yours on a machine that
  passes the preflight, and record it in your PR.
