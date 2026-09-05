---
"apollo": minor
---

global_chat: pass input attachments to subagents verbatim, keep them out of history, and reject oversized ones instead of trimming them. Attachment content may now arrive typed (a log's lines, a dataclip object) and is rendered by shape. Every ApolloError is tagged in Sentry by type, at warning level when the caller caused it
