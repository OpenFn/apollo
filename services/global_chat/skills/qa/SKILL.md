---
name: qa
description: Review a workflow against OpenFn conventions and report what should change
---

Review the workflow the user is asking about and report what should change. Do
not edit it unless they ask.

1. Read the workflow structure and the job code of every step.
2. Check each step for: unhandled errors, hardcoded values that belong in
   state or credentials, operations that do not exist in the step's adaptor,
   and steps doing work that belongs in another step.
3. Report findings worst first, each naming the step and what to change.
4. Say plainly if you found nothing worth changing.
