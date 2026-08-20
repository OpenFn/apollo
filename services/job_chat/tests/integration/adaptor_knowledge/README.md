# Adaptor knowledge probes

Thirty cases that ask job_chat something whose correct answer lives in one
specific, named place in an adaptor's documentation, then check the answer with
a regex. They exist to give anyone working on adaptor-docs retrieval a
scoreboard: a number that should go up as the method improves.

Many of them fail today. That's the point — a suite that already passes
measures nothing.

## Baseline

Measured on 2026-08-20, `job_chat` unchanged, docs seeded as described below:

| Group | Pass |
|---|---|
| `signatures` (controls) | 3/3 |
| `functions` | 4/6 |
| `interfaces` | 4/7 |
| `namespaces` | **1/6** |
| `other` | 2/3 |
| `version` | 2/2 run (3 skipped, old versions unavailable locally) |
| **Total** | **16/27** |

Treat this as approximate. The model is stochastic and cases near the boundary
flip between runs — `iface.salesforce-bulk-failonerror` passed one run and
failed the next. Re-baseline before and after any change rather than comparing
against these numbers directly.

`namespaces` at 1/6 is the standout, and the cause is concrete: see the last
section.

## Running them

```bash
poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s
```

One group at a time:

```bash
poetry run pytest services/job_chat/tests/integration/adaptor_knowledge -s -k interfaces
```

Each case costs one job_chat call against the live Anthropic API. The run
prints a per-group scoreboard at the end.

## Why here, and not under `acceptance/`

Three reasons, in order of weight:

**These are pass/fail, not judged.** Every assertion is a regex over the
response. Nobody has to read 30 verdicts to learn what happened — you read one
scoreboard line per group. The `acceptance/` tier is built around
`spec_collector` turning markdown specs into LLM-judged items, which is the
right tool when "is this answer good?" needs judgement, and the wrong one when
the question is "does the string `body:` appear in the generated code?".

**The tier marker follows the directory.** The repo-root `conftest.py` applies
`unit` / `service` / `integration` / `acceptance` based on which of those names
appears in the test's path. These tests hit a live LLM and Postgres, which is
the repo's own definition of `integration` ("hits real external services...
Manual/nightly"). Putting them under `integration/` gets the correct marker
with no new machinery.

**Excluding them is automatic.** They aren't in an `acceptance/` directory, so
`spec_collector` never collects them and an acceptance run never touches them.
Nothing to remember, no flag to pass.

On the nesting question: a topic folder *inside* a tier folder is fine and is
what the marker logic expects. The thing to avoid is the inverse — tier folders
nested under a topic folder — which would still technically work (the root
conftest matches any path segment) but reads backwards.

If a probe ever needs real judgement rather than a string match, it belongs in
`../../acceptance/` as a markdown spec, alongside
`bugs/test_repro_gmail_sendmessage_keys.md`. Splitting by *how you assert*
rather than by *what you're testing* is what keeps both harnesses simple.

## Layout

| File | What it is |
|---|---|
| `cases.py` | The 30 cases as data. Edit this to add or tune probes. |
| `test_adaptor_knowledge.py` | Parametrized runner, regex assertions, scoreboard. |
| `conftest.py` | Skips a case when its adaptor version has no docs. |
| `seed_docs.py` | Dev workaround for machines where jsdoc can't run. |

## The groups

| Group | n | Doc location being probed |
|---|---|---|
| `signatures` | 3 | The function list job_chat already injects. **Controls — these should pass.** |
| `functions` | 6 | `## Functions` — parameter names, order, examples |
| `interfaces` | 7 | `## Interfaces` — `@typedef` property names |
| `namespaces` | 6 | `## <namespace>` — `tracker.*`, `bulk1/2.*`, `util.*`, `http.*` |
| `other` | 3 | `configuration-schema` and the README |
| `version` | 5 | Behaviour that differs between two pinned versions |

The `signatures` group is the baseline. If those fail, something is wrong with
the fixture rather than with retrieval.

Four `version` cases are deliberate inverses of a case in another group — the
same question, a different pin, and the opposite correct answer:

| Latest-version case | Old-version inverse |
|---|---|
| `fn.http-post-data-positional` (7.3.2, `post(path, data)`) | `ver.http6-post-body-option` (6.5.4, `{body: ...}`) |
| `ns.dhis2-util-findattributevalue` (8.2.1, `util.` prefix) | `ver.dhis2-6-findattributevalue-toplevel` (6.3.4, no prefix) |
| `ns.salesforce-bulk2-insert` (9.1.1, `bulk2.insert`) | `ver.salesforce4-bulk-toplevel` (4.8.6, `bulk()`) |

A method that just dumps the latest docs will pass one side of each pair and
fail the other. That's the pair's job.

## Adding a case

Append a `Case` to the right list in `cases.py`. Fill in `doc_ref` with the
exact section the answer comes from, and `why` with the wrong answer you
expect. Both print on failure, which is what makes a red run actionable rather
than just red.

Keep `target="code"` for anything that asks for code. Prose discussing a wrong
key ("you might reach for `text:`, but...") would otherwise trip a `forbid`.

## Adaptor docs have to be present

A case is only meaningful if job_chat receives a real adaptor block. When the
docs are missing the prompt quietly degrades to "The user is using an OpenFn
Adaptor to write the job.", so `conftest.py` skips those cases rather than
letting them fail for the wrong reason.

Where `adaptor_apis` works, job_chat auto-loads on first use and there is
nothing to do. Where it doesn't — notably macOS under bun, where jsdoc dies on
`Module.wrapper` (see `JSDOC_BUN_ERROR.md`) — seed the table first:

```bash
poetry run python services/job_chat/tests/integration/adaptor_knowledge/seed_docs.py
```

That pulls the pre-built doclet feed the docsite indexer already uses and
pushes it through the real ingest functions, so the rows match what the live
pipeline would write. It only covers each adaptor's **latest** version, so the
old pins in the `version` group still skip unless that version is already in
your database.

## What the failures are telling you

Two upstream causes account for most of them, both verified in the code:

1. `job_chat/prompt.py` injects only the `signature` column. The
   `function_data` JSONB alongside it already holds descriptions, parameter
   docs and examples — nothing reads them.
2. `load_adaptor_docs.filter_function_docs` keeps only `function` /
   `external-function` / `external` doclets, so `@typedef` blocks — the only
   definition of option-object property names — are never stored.

There is also a third, narrower one worth fixing on its own: the namespace
prefix is stored in `function_name` (`bulk1.insert`) but not in `signature`
(`insert(sObject, records, options)`), and only the signature is injected. The
salesforce block therefore lists `insert(...)` three times with no way to tell
the variants apart, and shows `get`/`post`/`request` as if they were top-level
when they are `http.*`.
