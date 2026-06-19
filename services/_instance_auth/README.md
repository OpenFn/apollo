# Instance auth

Gates Apollo's `/services/*` endpoints so that only known Lightning instances can
call them, and makes Apollo use **its own per-client Anthropic API key** for each
request rather than trusting anything the caller sends.

This directory is not a mounted service (the leading `_` keeps it off the HTTP
router). It holds the schema and provisioning scripts; the actual gate lives in
`platform/src/middleware/auth.ts`.

## How it works

- The credential is the **`api_key` the caller already sends in the request
  body** — the same field Lightning sends today. There is no bearer token, no
  `Authorization` header, and **no change required on the Lightning side**.
- A single Postgres table, `lightning_clients`, is the allow-list. Each row has a
  `name`, the **SHA-256 hash** of that client's `api_key` (never the plaintext),
  and an optional `anthropic_api_key`.
- On every `/services/*` request the server reads `api_key` from the body,
  hashes it, and looks for a matching row. Missing or no match → `401
  UNAUTHORIZED`.
- The inbound `api_key` is treated **purely as a credential and is never
  forwarded to the LLM**. On a match it is replaced with the client's stored
  `anthropic_api_key`, so all LLM usage for that request bills to the key Apollo
  controls. If the column is `NULL`, the inbound key is **stripped** and Apollo
  falls back to its global `ANTHROPIC_API_KEY`. Either way the caller's key
  cannot pass through.
- **Performance:** the client list is cached in memory and refreshed on a ~60s
  TTL, so the database is queried at most once per minute per process, never on
  the per-request path to Anthropic. The per-request cost is a hash plus a map
  lookup. The trade-off is that revocations/rotations take up to ~60s to take
  effect (see Managing clients).
- **Opt-in / backward compatible:** auth is active only when the `INSTANCE_AUTH`
  environment variable is set (e.g. `INSTANCE_AUTH=true`). Otherwise the server
  stays open exactly as before and the caller's `api_key` passes through
  untouched. When auth is enabled but this table can't be reached, the gate
  **fails closed** (every external caller gets `401`) rather than silently
  opening up.
- The health endpoints (`/livez`, `/status`, `/`) sit outside `/services/*` and
  are never gated. Internal Apollo-to-Apollo `apollo()` calls are exempt via a
  per-process internal token (`APOLLO_INTERNAL_TOKEN`), not by network position.

## Setting up a client

`provision_client.ts` is the canonical way to add a Lightning client: it mints the
credential, hashes it, and encrypts the client's Anthropic key in one step.

1. Create the table (once):

   ```sh
   set -a; . ./.env; set +a
   psql "$POSTGRES_URL" -f services/_instance_auth/schema.sql
   ```

2. Set a master encryption key in `.env` (once) — `provision_client.ts` uses it to
   encrypt each client's Anthropic key at rest:

   ```sh
   echo "APOLLO_ENC_KEY=$(openssl rand -base64 32)" >> .env
   ```

3. Provision the client with a name and the Anthropic key Apollo should use for it:

   ```sh
   set -a; . ./.env; set +a
   bun services/_instance_auth/provision_client.ts <client-name> <sk-ant-...>
   ```

   This prints the `api_key` to give the Lightning instance and a ready-to-run
   `psql` `INSERT`. Run that `INSERT` to add the row.

4. Enable auth: set `INSTANCE_AUTH=true` in Apollo's environment and restart. The
   startup log shows `Apollo instance auth ENABLED`. (If `INSTANCE_AUTH` is set but
   the table is missing, the log warns and every external caller is rejected.)

5. Give the printed `api_key` to the Lightning instance. It keeps sending it as
   `api_key` exactly as it does today — no other Lightning-side change.

## Managing clients

Manage rows directly in the DB. Changes are picked up within ~60s (the server
caches the client list briefly); restart Apollo to apply a revocation immediately.

- **Revoke:** `DELETE FROM lightning_clients WHERE name = '...';`
- **Rotate a credential / change the Anthropic key:** re-run `provision_client.ts`
  and apply its output as an `UPDATE` for the existing `name` (it prints an
  `INSERT` — swap the verb).

### Lower-level scripts

`provision_client.ts` is built from two primitives, occasionally useful on their
own — e.g. to add a client whose `anthropic_api_key` is `NULL` (so it uses Apollo's
global `ANTHROPIC_API_KEY`), which `provision_client.ts` doesn't cover:

- `hash_token.py <api-key>` — hash (or, with no argument, mint) just the credential.
- `encrypt_key.ts <sk-ant-...>` — encrypt just an Anthropic key to an `enc:v1:…`
  value.

## At-rest encryption

`anthropic_api_key` is stored encrypted (AES-256-GCM) when written via
`provision_client.ts`/`encrypt_key.ts`; plaintext rows are still accepted for
backward compatibility.

- **Fail closed.** If an `enc:v1:` row can't be decrypted (wrong/missing
  `APOLLO_ENC_KEY` or corrupt value), that client is dropped from the allow-list
  and its requests get `401` — Apollo never falls back to the global key for an
  encrypted-but-undecryptable row. A `NULL` key still means "use the global key".
- **Rotation** is manual: re-encrypt every `enc:v1:` row with the new key, then
  swap `APOLLO_ENC_KEY` and restart.
- **What it protects.** The ciphertext is useless without `APOLLO_ENC_KEY`, so this
  guards DB dumps, backups, read replicas, and accidental `SELECT`s in logs. It
  does **not** protect a full Apollo host/process compromise: the running process
  necessarily holds both the key and the decrypted values in memory. Protect the
  table at rest (restricted access, DB encryption) regardless.

The clients' `api_key` credentials are only ever stored and compared as hashes.
