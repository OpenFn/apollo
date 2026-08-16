---
"apollo": patch
---

echo: mask sensitive values rather than reflecting the whole payload back to
the caller and into the logs. The shared mask now covers every field the
server may fill in, and recognises both provider key formats by shape
