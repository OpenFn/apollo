# Adaptor knowledge probes

Thirty cases that ask job_chat something whose correct answer lives in one
specific, named place in an adaptor's documentation, then check the answer with
a regex. They exist to give anyone working on adaptor-docs retrieval a
scoreboard: a number that should go up as the method improves.

Many of them fail today. That's the point — a suite that already passes
measures nothing.

## Baseline

**Not yet established.** The numbers this suite produced during development came
from a machine where the docs pipeline couldn't run, on hand-built fixture rows,
so they don't describe the real service and have been removed rather than left
here to be trusted.

Set the baseline by running the suite once, unchanged, on a machine where
`adaptor_apis` works, and record the scoreboard it prints. Do that before any
retrieval change, not after.

Two things to know when you do:

- The model is stochastic and cases near the boundary flip between identical
  runs. A one- or two-point move is noise. Run it more than once.
- `namespaces` was by far the weakest group in every development run, and the
  cause is concrete rather than statistical: see the last section.

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
| `conftest.py` | Prints the scoreboard at the end of the run. |
| `scoreboard.py` | The tally the runner writes and conftest prints. |

## The groups

| Group | n | Doc location being probed |
|---|---|---|
| `signatures` | 3 | The function list job_chat already injects. **Controls — these should pass.** |
| `functions` | 6 | `## Functions` — parameter names, order, examples |
| `interfaces` | 7 | `## Interfaces` — `@typedef` property names |
| `namespaces` | 6 | `## <namespace>` — `tracker.*`, `bulk1/2.*`, `util.*`, `http.*` |
| `other` | 3 | `configuration-schema` and the README |
| `version` | 5 | Behaviour that differs between two pinned versions |

The `signatures` group is the baseline. If those fail, job_chat isn't getting
an adaptor block at all and no other number in the run means anything.

Four `version` cases are deliberate inverses of a case in another group — the
same question, a different pin, and the opposite correct answer:

| Latest-version case | Old-version inverse |
|---|---|
| `fn.http-post-data-positional` (7.3.2, `post(path, data)`) | `ver.http6-post-body-option` (6.5.4, `{body: ...}`) |
| `ns.dhis2-util-findattributevalue` (8.2.1, `util.` prefix) | `ver.dhis2-6-findattributevalue-toplevel` (6.3.4, no prefix) |
| `ns.salesforce-bulk2-insert` (9.1.5, `bulk2.insert`) | `ver.salesforce4-bulk-toplevel` (4.8.6, `bulk()`) |

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

A case only measures anything if job_chat receives a real adaptor block. When
the docs are missing the prompt quietly degrades to "The user is using an
OpenFn Adaptor to write the job." and every case fails for a reason that has
nothing to do with retrieval.

There is no fixture to set up: job_chat auto-loads an adaptor's docs on first
use (`download_adaptor_docs` defaults to true), through the same pipeline
production uses. Run the suite somewhere that pipeline works.

It does not work on macOS under bun, where jsdoc dies on `Module.wrapper` (see
`JSDOC_BUN_ERROR.md`). A full-red run there is a broken toolchain, not a score.
Check before believing a number:

```bash
psql "$POSTGRES_URL" -c "SELECT adaptor_name, version, count(*) FROM adaptor_function_docs GROUP BY 1,2 ORDER BY 1,2"
```

Don't hand-populate that table to get a green-ish run. Rows written from
anything other than the real pipeline make the score unreadable — you no longer
know whether a change moved retrieval or just moved the fixture.
