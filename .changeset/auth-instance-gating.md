---
"apollo": minor
---

Add optional instance auth: gate `/services/*` behind a per-client bearer token
(opt-in via `INSTANCE_AUTH`), inject each client's API key from the
`lightning_clients` table, trust internal service-to-service calls via
`APOLLO_INTERNAL_SECRET`, and fail closed when enabled but the client table is
unreachable. Requires Bun >= 1.2.
