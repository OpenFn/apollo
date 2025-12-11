---
"apollo": minor
---

- Add `load_adaptor_docs` and `search_adaptor_docs` services, which use postgres
  to cache and search docs data
- Use new adaptor docs lookup in `job_chat`, for faster, leaner and better docs
  lookup
