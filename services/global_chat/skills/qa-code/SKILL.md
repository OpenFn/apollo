---
name: qa-code
description: A thorough review of one step's code, fixing what's wrong within it. Use when the user considers the step done and hands it over for a full review, not for a quick check or one specific change.
metadata:
  agent: job_code
---

Review this step's code and fix what's wrong within it. Hold it to the spec and
the user, and check it against the steps it reads from and writes for.

Cover:
- doing what the spec or user asks of this step;
- how it uses state: operations at the top level, never nested in callbacks;
  callbacks that return state; state read lazily (`$` or a function) in
  operation arguments; async work done through operations, not `async`/`await`
  or promises;
- what it passes on: only plain JSON leaves the step, so helpers are defined in
  the step rather than stored on state; only what the next step needs, with no
  leftover or intermediate keys; no personal data logged or left on the final
  state, which OpenFn doesn't scrub;
- what it takes in: incoming data validated before it's written, and a failing
  system or malformed response handled rather than passed on;
- structure: several small operations that each do one thing rather than one
  large `fn()`, and no `fn()` wrappers that add nothing;
- its adaptor: the adaptor's own functions rather than raw HTTP, used
  correctly, and cursors set and advanced as intended;
- loops: state overwritten inside them, items or shared objects mutated while
  iterating, `each()` used as intended;
- errors swallowed or never surfaced, and one bad record failing a whole batch
  or disappearing silently, unless that's intended;
- work that runs away: unbounded retries, loops or calls;
- credentials written into code, values hardcoded that belong in
  configuration, and anything left over from testing;
- comments that contradict the code.

Report cleanup (duplication, dead code, unclear names, magic numbers) rather
than making it. Reply briefly with what you fixed and what should still change.
