---
"apollo": minor
---

Add an instance-auth gate to `/services/*` that maps a known caller's `api_key`
to a per-client Anthropic key.

The inbound `api_key` already sent in the request body is hashed (SHA-256) and
looked up in a new `lightning_clients` table (via `APOLLO_CLIENTS_DB_URL`, or
`POSTGRES_URL` if that's unset, so the credentials can live in their own database
in production). On a known match
the credential is swapped for the client's stored `anthropic_api_key` (plaintext
or `enc:v1:` AES-256-GCM, decrypted with `APOLLO_ENC_KEY`) and never forwarded to
the LLM; an unknown `sk-ant-`-shaped key is forwarded unchanged (bring-your-own),
and an unknown non-`sk-ant-` key is rejected with `401`. Lookups are cached
in-process (~60s, single-flight with stale-while-revalidate). Internal
Apollo-to-Apollo calls are exempt via a per-process `APOLLO_INTERNAL_TOKEN`.

Backward compatible: existing callers that pass an `sk-ant-` key are unaffected.
Operators provision clients with the new `client` CLI in `platform/src/auth/`.
