---
"apollo": patch
---

workflow_chat: match an adaptor name against the available list whether or not it
carries a version, skip validation when the list comes back empty rather than
calling every adaptor invented, and report a name that is genuinely off the list
to Sentry
