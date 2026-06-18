# Per-client API key mapping

Lets a client (e.g. a specific Lightning instance) call Apollo with an
**OpenFn-issued token** instead of holding a real provider key. Apollo recognises
the token and uses the key it holds for that client, so the client doesn't need a
provider key of its own.

This directory is not a mounted service (the leading `_` keeps it off the HTTP
router). It is just the schema and a helper script; the logic lives in
`platform/src/middleware/client_keys.ts`.

## How it works

- A single Postgres table, `lightning_clients`, lists the known clients. Each row
  has a `name`, the **SHA-256 hash** of its token (never the plaintext), and an
  optional `anthropic_api_key`.
- On each `/services/*` request, Apollo hashes the incoming `api_key` and looks
  for a matching row. On a match it swaps in that client's `anthropic_api_key`
  (or, if `NULL`, falls back to the global `ANTHROPIC_API_KEY`). **No match means
  it's left untouched**, so a caller passing its own provider key still works.
- **Opt-in / backward compatible:** it activates only when this table is
  provisioned. Without it, every request passes through exactly as before. There
  is no env flag. It needs **Bun >= 1.2** (`Bun.SQL`).
- Because it only *recognises* tokens and never rejects anyone, multiple clients
  can safely share one Apollo.

> This is recognition, not a gate. It does not restrict who may call Apollo. A
> hard "reject unknown callers" gate is a separate, future capability.

## Provisioning a client

1. Make sure `POSTGRES_URL` is set, then create the table:

   ```sh
   psql "$POSTGRES_URL" -f services/_instance_auth/schema.sql
   ```

2. Mint a token for the client and get its hash:

   ```sh
   poetry run python services/_instance_auth/hash_token.py
   ```

   This prints a plaintext token (give it to the client), the hash to store, and
   a ready-to-edit `INSERT`.

3. Insert the row (set `name` and the key Apollo should use for them):

   ```sql
   INSERT INTO lightning_clients (name, auth_token_hash, anthropic_api_key)
   VALUES ('my-lightning-instance', '<hash>', 'sk-ant-...');
   ```

4. Configure that client to send the **token** as its `api_key`. For a Lightning
   instance that's the existing `AI_ASSISTANT_API_KEY` env var, set it to the
   token instead of a provider key. No code change on the client side.

## Managing clients

There is no CLI — manage rows directly in the DB:

- **Revoke a client:** `DELETE FROM lightning_clients WHERE name = '...';`
- **Rotate a token:** mint a new one with `hash_token.py` and
  `UPDATE lightning_clients SET auth_token_hash = '<new-hash>' WHERE name = '...';`
- **Change a client's key:**
  `UPDATE lightning_clients SET anthropic_api_key = '...' WHERE name = '...';`

Changes are picked up within ~60s (Apollo caches the client list briefly).

## Note

The `anthropic_api_key` is stored as plaintext because Apollo must be able to use
it. Protect this table at rest (DB encryption, restricted access) accordingly. The
tokens themselves are only ever stored as hashes.
