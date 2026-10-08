---
name: qa-code
description: Review and fix one step's code on its own terms, as part of a workflow review
metadata:
  agent: job_code
---

Review this step and fix what's wrong within it, so that it's right on its own
terms. Other steps are being reviewed at the same time, and fitting them
together comes later, so hold the step to the spec and the user rather than to
what other steps currently do.

Cover:
- valid code that follows OpenFn job-writing conventions and uses its adaptor
  correctly;
- doing what the spec or user asks of this step;
- state overwritten inside loops;
- errors swallowed or never surfaced;
- values hardcoded that belong in configuration;
- comments that contradict the code.

Report cleanup (duplication, dead code, unclear names) rather than making it.
Reply briefly with what you fixed and what should still change.
