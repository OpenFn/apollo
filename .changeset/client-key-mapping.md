---
"apollo": minor
---

Add optional per-client API key mapping. When the `lightning_clients` table is
provisioned (via `POSTGRES_URL`), an incoming `api_key` that matches a known
client token is swapped for the key Apollo holds for that client; unrecognised
keys pass through unchanged. This lets a client authenticate with an
OpenFn-issued token instead of holding a real provider key, while other callers
are unaffected. Opt-in purely by provisioning the table; requires Bun >= 1.2.
