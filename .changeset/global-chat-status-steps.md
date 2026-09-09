---
"apollo": patch
---

Global chat: report which workflow steps a settled status acted on, as data
rather than as names inside the sentence, so a client can attach per-step
detail without parsing the prose. Each status also carries a shorter summary
for clients that render that detail, so step names are not printed twice. Both
fields are optional. Step names are no longer title-cased either, so a step the
user called "Transform data" is no longer reported as "Transform Data"
