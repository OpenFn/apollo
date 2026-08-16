---
"apollo": patch
---

Mask sensitive values on their way out of a service, rather than relying on
each one to remember: service loggers mask what they emit, echo masks what it
returns, and the error envelope masks the exception text. The shared mask now
covers every field the server may fill in, and no longer matches ordinary
hyphenated words
