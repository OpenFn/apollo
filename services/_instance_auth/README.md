# Instance auth

Gates Apollo's `/services/*` endpoints so that only known Lightning instances can
call them, and makes Apollo use **its own per-client Anthropic API key** for each
request rather than trusting anything the caller sends.

This directory is not a mounted service (the leading `_` keeps it off the HTTP
router). It is just the schema and a helper script; the actual gate lives in
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

## Enabling it

1. Make sure `POSTGRES_URL` is set, then create the table:

   ```sh
   psql "$POSTGRES_URL" -f services/_instance_auth/schema.sql
   ```

2. Get the SHA-256 hash of the `api_key` a given Lightning instance sends:

   ```sh
   poetry run python services/_instance_auth/hash_token.py <the-api-key>
   ```

   (Run with no argument to instead mint a fresh credential to hand to the
   instance.) This prints the hash to store and a ready-to-edit `INSERT`.

3. Insert the row. Set `name`, the hash, and the Anthropic key Apollo should use
   for this client (leave `anthropic_api_key` as `NULL` to use Apollo's global
   key):

   ```sql
   INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)
   VALUES ('my-lightning-instance', '<hash>', 'sk-ant-...');
   ```

   To store the Anthropic key encrypted instead of in the clear, see
   [Encrypting the stored Anthropic keys](#encrypting-the-stored-anthropic-keys-optional)
   below and paste the `enc:v1:…` value in place of `'sk-ant-...'`.

4. Set `INSTANCE_AUTH=true` in Apollo's environment and restart. The startup log
   shows `Apollo instance auth ENABLED`. (If `INSTANCE_AUTH` is set but the table
   is missing, the log warns and every external caller is rejected.)

No Lightning-side configuration is needed: it keeps sending its `api_key` exactly
as it does now.

## Managing clients

There is no CLI — manage rows directly in the DB:

- **Revoke a client:** `DELETE FROM lightning_clients WHERE name = '...';`
- **Rotate a credential:** hash the new `api_key` with `hash_token.py` and
  `UPDATE lightning_clients SET auth_token_hash = '<new-hash>' WHERE name = '...';`
- **Change the Anthropic key Apollo uses for a client:**
  `UPDATE lightning_clients SET anthropic_api_key = '...' WHERE name = '...';`

Changes are picked up within ~60s (the server caches the client list briefly). If
you need a revocation to take effect immediately, restart Apollo.

## Encrypting the stored Anthropic keys (optional)

By default `anthropic_api_key` is stored as plaintext. You can instead encrypt it
at rest with AES-256-GCM so a DB dump/backup/replica leak doesn't expose live
keys:

1. Generate a 32-byte master key and set it in Apollo's environment:

   ```sh
   openssl rand -base64 32          # → put the output in APOLLO_ENC_KEY
   ```

2. Encrypt a key to get the value to store:

   ```sh
   APOLLO_ENC_KEY=<the-base64-key> \
     bun services/_instance_auth/encrypt_key.ts sk-ant-...
   ```

   This prints an `enc:v1:…` blob (and a ready-to-edit `INSERT`). Use it in place
   of the plaintext key:

   ```sql
   UPDATE lightning_clients SET anthropic_api_key = 'enc:v1:...' WHERE name = '...';
   ```

3. Restart Apollo with `APOLLO_ENC_KEY` set. It decrypts each key once per ~60s
   cache refresh.

Notes:

- **Backward compatible / opt-in.** Plaintext rows keep working; only `enc:v1:`
  rows need `APOLLO_ENC_KEY`. You can migrate one client at a time.
- **Fail closed.** If an `enc:v1:` row can't be decrypted (wrong/missing
  `APOLLO_ENC_KEY` or corrupt value), that client is dropped from the allow-list
  and its requests get `401` — Apollo never silently falls back to the global key
  for an encrypted-but-undecryptable row. A `NULL` key still means "use the
  global key" as before.
- **Rotation** is manual: decrypt and re-encrypt every `enc:v1:` row with the new
  key, then swap `APOLLO_ENC_KEY` and restart.
- **What it protects.** The ciphertext is useless without `APOLLO_ENC_KEY`, so
  this guards DB dumps, backups, read replicas, and accidental `SELECT`s in logs.
  It does **not** protect a full Apollo host/process compromise: the running
  process necessarily holds both the key and the decrypted values in memory
  (Apollo must use the key to call Anthropic). Continue to protect the table at
  rest (restricted access, DB encryption) regardless.

The clients' `api_key` credentials are only ever stored and compared as hashes.
