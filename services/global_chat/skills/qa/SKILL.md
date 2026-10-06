---
name: qa
description: Review a workflow against what it is meant to do and report what should change
---

Review the workflow against what it's meant to do, taken from the user, a spec
or ticket they've shared, or the workflow itself. If you can't tell, ask. With
a spec, say which parts are met, partly met or missing.

Work outwards in three stages:

1. Each step on its own. Have the job code agent review and fix every step in
   parallel. The goal is that each step is right on its own terms: valid code,
   correct use of its adaptor, and doing what the spec or user asks of it.
   Making the steps fit together is the next stage's job.
2. One run, end to end. Read every step's code yourself with
   `inspect_job_code` and follow the data from the trigger to the last step. Each step should read what the steps before it
   actually write, under the same names and in the same shape; edges should
   route data where it should go; and no two steps should do the same work. To
   fix a mismatch, decide which side is right and give every affected step the
   same instruction.
3. Many runs, once live. Data lost, duplicated, corrupted or exposed without
   anyone noticing (often a re-run that creates duplicates, a cursor or paging
   that skips records, or a lookup that assumes exactly one match) matters
   more than a step that fails loudly, as does work that runs away (unbounded
   retries, loops or calls). So does anything left over from testing that
   shouldn't go live.

If dataclips are attached, check that the output means what the input meant.

Tell the user what you fixed and what should still change, worst first, with
the step. Say when a problem is inferred from the code rather than seen in the
data. If nothing needs changing, say so. On a follow-up review, say which
earlier issues are fixed and which aren't. Propose a fix first when it would
change behaviour beyond the problem or needs the user's decision.
