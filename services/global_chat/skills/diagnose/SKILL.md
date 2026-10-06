---
name: diagnose
description: Diagnose a failed workflow run from its logs, dataclips and workflow YAML
---

Diagnose why the run failed, or why it didn't do what the user expected.

Work from the run logs and dataclips attached to this turn; if none are
attached, say what you need and stop. You can't rerun anything, so a cause the
evidence doesn't show is a hypothesis, and you should call it one.

Find the error that started the failure and trace it into the code: which step
and operation raised it, and what data it was handling (often state a previous
step didn't write under that name, an adaptor overwriting `data`, or input
carried over from an earlier scheduled run). Point outside the code (a
credential, the connection, a target system's configuration) when the error
itself shows the cause is there. If the platform stopped the run (killed for
time, memory or state size, or lost), the cause is usually how much the code
holds or how long it runs rather than a wrong line, and missing logs aren't
evidence of a code bug.

Look past the first failure too: read the later steps against the data they
would receive. Mention what you only suspect as something to watch.

Tell the user what failed, why, and what showed you. If you're not certain,
give the likely causes and the one check that would tell them apart. When the
fix is contained, make it, along with anything you know is wrong in the later
steps. When it would change behaviour beyond the bug or needs the user's
decision, propose it first.
