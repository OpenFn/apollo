---
"apollo": patch
---

Raise the server's socket idle timeout back to 255s so long-running SSE
streams are no longer cut off while a model is thinking
