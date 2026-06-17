# Instance auth

Gates Apollo's `/services/*` endpoints so that only known Lightning instances can
call them, and makes Apollo use **each client's own Anthropic API key** for that
client's requests.

This directory is not a mounted service (the leading `_` keeps it off the HTTP
router). It is just the schema and a helper script; the actual gate lives in
`platform/src/middleware/auth.ts`.

## How it works

- A single Postgres table, `lightning_clients`, lists the allowed clients. Each row
  has a `name`, the **SHA-256 hash** of its bearer token (never the plaintext), and
  an optional `anthropic_api_key`.
- On every `/services/*` request the server reads `Authorization: Bearer <token>`,
  hashes it, and looks for a matching row. No match → `401 UNAUTHORIZED`.
- On a match, the client's `anthropic_api_key` (if set) is injected into the
  request payload as `api_key`, so all LLM usage for that request bills to the
  client. If the column is `NULL`, Apollo falls back to its global
  `ANTHROPIC_API_KEY`.
- **Opt-in / backward compatible:** auth is active only when the `INSTANCE_AUTH`
  environment variable is set (e.g. `INSTANCE_AUTH=true`). Otherwise the server
  stays open exactly as before. When auth is enabled but this table can't be
  reached, the gate **fails closed** (every external caller gets `401`) rather
  than silently opening up.
- Loopback callers (`127.0.0.1`/`::1`) and the health endpoints (`/livez`,
  `/status`, `/`) are exempt.

## Enabling it

1. Make sure `POSTGRES_URL` is set, then create the table:

   ```sh
   psql "$POSTGRES_URL" -f services/_instance_auth/schema.sql
   ```

2. Mint a token for a Lightning instance and get its hash:

   ```sh
   poetry run python services/_instance_auth/hash_token.py
   ```

   This prints a plaintext token (give it to the Lightning instance), the hash to
   store, and a ready-to-edit `INSERT`.

3. Insert the row (set `name` and the client's Anthropic key):

   ```sql
   INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)
   VALUES ('my-lightning-instance', '<hash>', 'sk-ant-...');
   ```

4. Configure that Lightning instance to send `Authorization: Bearer <token>` on
   its Apollo requests.

5. Set `INSTANCE_AUTH=true` in Apollo's environment and restart. The startup log
   shows `Apollo instance auth ENABLED`. (If `INSTANCE_AUTH` is set but the table
   is missing, the log warns and every external caller is rejected.)

## Managing clients

There is no CLI — manage rows directly in the DB:

- **Revoke a client:** `DELETE FROM lightning_clients WHERE name = '...';`
- **Rotate a token:** mint a new one with `hash_token.py` and
  `UPDATE lightning_clients SET auth_token_hash = '<new-hash>' WHERE name = '...';`
- **Change a client's key:**
  `UPDATE lightning_clients SET anthropic_api_key = '...' WHERE name = '...';`

Changes are picked up within ~60s (the server caches the client list briefly).

## Note

The `anthropic_api_key` is stored as plaintext because Apollo must be able to use
it. Protect this table at rest (DB encryption, restricted access) accordingly. The
bearer tokens themselves are only ever stored as hashes.
