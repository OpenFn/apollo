---
name: qa
description: Review a workflow against what it is meant to do and report what should change
---

Review the workflow against what it's meant to do, taken from the user, a spec
or ticket they've shared, or the workflow itself. If you can't tell, ask. With
a spec, say which parts are met, partly met or missing, including edge cases
it implies but doesn't state.

Read first, then review every step, fixing what's wrong only if the user has
asked you to.

1. Read every step's code yourself with `inspect_job_code` and follow the data
   from the trigger to the last step, looking at what's below. Where steps
   don't fit, decide which side is right, so each step's fix can be settled
   before anything changes.

2. Have the job code agent review every step in parallel with the `qa-code`
   skill, which covers everything within a step. Your message carries what
   only you know: the contract each step keeps with its neighbours (what it
   reads and writes, under which names), which side of a mismatch it owns,
   that the other steps are being handled at the same time so it covers only
   its own, and what this conversation adds, such as what the spec asks of the
   step, limits the user has set, or that the user wants the changes made.
   Leave everything else in the step to the job code agent. Have the workflow
   agent review the triggers, edges and adaptor choices too, telling it
   whether the user wants the changes made. Workflow changes go through it.

3. After making changes, read the changed steps again to confirm they now fit
   together.

How the steps fit together:
- the trigger is the right kind and enabled as intended;
- each step runs after everything it depends on;
- each step reads what the steps before it actually write, under the same
  names, in the same shape, and as plain JSON, since anything else is lost
  between steps;
- edges route data where it should go, so a failed or unmatched record can't
  fall through;
- no two steps do the same work;
- each step uses its system's own adaptor where one exists rather than plain
  HTTP;
- names other workflows rely on, such as collections, match exactly.

How it behaves live, over many runs. What fails quietly matters more than what
fails loudly, and these usually need the user's decision:
- a re-run that creates duplicates;
- a cursor or paging that skips records;
- a lookup that assumes exactly one match;
- adaptors on `@latest`, which can change under a live workflow and break it.
  The fix is to pin the version the workflow was tested on, which run logs
  often show; if you can't tell, say the pinned version is untested.

If dataclips are attached, check that the output means what the input meant.

Tell the user what you changed, if anything, then what should still change:
- Group it by whether it must, should or could change, worst first, naming the
  step and the operation. Anything that breaks, loses or exposes data, or
  breaks OpenFn's job-writing conventions, is a must.
- Offer cleanup as could-change in a line or two, and do it only if the user
  wants that kind of tidying.
- List a problem shared by several steps once.
- For a suggested change, show only the lines that change, with the
  recommended fix and any alternative in a line.
- Skip style nits a formatter would catch and speculative performance
  concerns.
- Say when a problem is inferred from the code rather than seen in the data.
- If nothing needs changing, say so. On a follow-up review, say which earlier
  issues are fixed and which aren't.

Then offer to make what should still change. When making changes, propose first any that would change behaviour beyond the
problem or need the user's decision, and once the user agrees to changes,
give each step the ones agreed for it, without the `qa-code` skill, rather
than reviewing it again. If you changed anything, remind the user to test the
workflow again before relying on it.
