# Instance auth

Restricts Apollo's `/services/*` endpoints so that only known Lightning instances
can call them, and makes Apollo use **its own per-client Anthropic API key** for each
request rather than trusting anything the caller sends.

This is server-layer code: the runtime auth hook, the shared hash, and the internal-call
token live here under `platform/src/auth/`; the operator tooling sits alongside in
`platform/src/auth/client/` (the `client` CLI). The `lightning_clients` table is
created and kept current by the migration runner (`platform/src/db/migrate.ts`,
migrations under `platform/migrations/`).

## How it works

- The credential is the **`api_key` the caller already sends in the request
  body** — the same field Lightning sends today. There is no bearer token, no
  `Authorization` header, and **no change required on the Lightning side**.
- A single Postgres table, `lightning_clients`, is the allow-list. Each row has a
  `name`, the **SHA-256 hash** of that client's `api_key` (never the plaintext),
  and an optional `anthropic_api_key`.
- On every `/services/*` request the server reads `api_key` from the body,
  hashes it, and looks for a matching row. The inbound `api_key` is treated
  **purely as a credential and is never forwarded to the LLM** on a known match.
- On a match it is replaced with the client's stored `anthropic_api_key`, so all
  LLM usage for that request bills to the key Apollo controls. If the column is
  `NULL`, the inbound key is **stripped** and Apollo falls back to its global
  `ANTHROPIC_API_KEY`. Either way the caller's key cannot pass through.
- **Performance:** lookups are cached per client on a ~60s TTL with single-flight,
  stale-while-revalidate refresh, so the database is queried at most once per
  minute per process per token, never on the per-request path to Anthropic. The
  per-request cost is a hash plus a map lookup.
- **Transparent / backward compatible (map-if-known-else-forward):** the auth hook
  is always active but only swaps in a key when it recognises the caller. An
  unrecognised key is forwarded unchanged if it is `sk-ant-`-shaped
  (bring-your-own key) and rejected (`401`) otherwise; a non-`sk-ant-` key is a
  likely Lightning credential that must not reach the LLM. A request with no
  `api_key` falls back to the global key. When this table can't be reached,
  known-client swaps don't resolve and every caller degrades to that forward
  path; it does **not** blanket-reject.
- The health endpoints (`/livez`, `/status`, `/`) sit outside `/services/*` and
  are never subject to the auth hook. Internal Apollo-to-Apollo `apollo()` calls are exempt via a
  per-process internal token (`APOLLO_INTERNAL_TOKEN`), not by network position.

## Where the clients table lives

The `lightning_clients` table is reached via **`APOLLO_CLIENTS_DB_URL`**, which falls
back to `POSTGRES_URL` when it isn't set. The TS auth code, the migration runner
(`bun run migrate`), and the `client` CLI all resolve the URL the same way, so they
always agree on which database they're touching.

- **Local dev:** set only `POSTGRES_URL`. The clients table, the auth code, and the
  Python docs services all share that one database, exactly as before this var
  existed. You don't need to set a second URL to get started.
- **Production:** point `APOLLO_CLIENTS_DB_URL` at a **separate** database (its own
  least-privilege user) so the per-client credentials (including the encrypted
  Anthropic keys) don't co-locate with the docs data on `POSTGRES_URL`. This is the
  advisable setup for any deployment holding real client secrets: a leak or a loose
  grant on the docs DB then doesn't expose the credentials table, and the clients DB
  can be locked down independently.

The Python docs services (`adaptor_function_docs`) always use `POSTGRES_URL` and are
unaffected by the split. One caveat to keep in mind: with the two URLs pointing at
different databases, the TS side (clients) and Python side (docs) genuinely live
apart, so when you run a migration or register a client, make sure
`APOLLO_CLIENTS_DB_URL` resolves to the database you mean. On startup Apollo logs
which one it opened (`clients DB: using APOLLO_CLIENTS_DB_URL` /
`...falling back to POSTGRES_URL`).

## The `client` CLI

`bun run client` is the canonical way to manage Lightning clients. It carries four
subcommands — `add` / `rotate` / `encrypt` / `verify`. Run them from the repo root
so Bun loads `.env` (`APOLLO_ENC_KEY`, and `APOLLO_CLIENTS_DB_URL` or `POSTGRES_URL`). The Anthropic key is read
from **stdin** (a pipe or an interactive prompt), never from `argv`, so it never
lands in shell history or `ps`; the client **name** is a positional argument.

1. Bring the schema up to date. The migration runner does this automatically at
   Apollo startup when a clients DB URL is set, so usually no step is needed. To run
   it on its own (e.g. before provisioning against a fresh DB):

   ```sh
   bun run migrate
   ```

   This applies only the platform/auth schema (`lightning_clients`, `_migrations`).
   The Python services own and self-initialise their own table
   (`adaptor_function_docs`), so `bun run migrate` does not and should not touch it.

2. Set a master encryption key in `.env` (once) — the CLI uses it to encrypt each
   client's Anthropic key at rest:

   ```sh
   echo "APOLLO_ENC_KEY=$(openssl rand -base64 32)" >> .env
   ```

3. Add the client with a name and the Anthropic key Apollo should use for it (key
   on stdin; needs a clients DB URL set too, since it writes the row itself):

   ```sh
   echo "$KEY" | bun run client add acme
   # or pull the key from a secret without it touching the shell:
   cat /run/secrets/anthropic | bun run client add acme
   ```

   This writes the row to `lightning_clients` and prints **only** the `api_key` to
   give the Lightning instance. No SQL to run by hand. Re-running `add` for an
   existing name fails with a "use `rotate`" message rather than a raw constraint
   error.

4. The client is active as soon as its row is in the table — there is no flag to
   set or restart needed. The startup log shows `Apollo instance auth:
   lightning_clients lookup ready.` once the DB is reachable. (If the table is
   missing or the DB is down, the log warns and callers fall to the forward path
   rather than being rejected; known-client swaps just won't resolve.)

5. Give the printed `api_key` to the Lightning instance. It keeps sending it as
   `api_key` exactly as it does today — no other Lightning-side change.

## Managing clients

- **Rotate the Anthropic key** (keeping the same `api_key`/credential, so the
  Lightning side needs no re-credentialling):

  ```sh
  echo "$NEWKEY" | bun run client rotate acme
  ```

- **Verify** that a client's stored key resolves under the current `APOLLO_ENC_KEY`
  — reports `decrypts` / `plaintext` / `global` (NULL) / `DECRYPT_FAILED`, and exits
  non-zero on failure:

  ```sh
  bun run client verify acme
  ```

- **Revoke:** `DELETE FROM lightning_clients WHERE name = '...';` directly in the
  DB. Changes are picked up within ~60s (the server caches each client briefly);
  restart Apollo to apply a revocation immediately.

### `encrypt` — the lower-level subcommand

`bun run client encrypt` prints the `enc:v1:…` value for the key on stdin and makes
**no DB write**. Useful for manual SQL / row-seeding — e.g. to add a client whose
`anthropic_api_key` is `NULL` (so it uses Apollo's global `ANTHROPIC_API_KEY`),
which `add` doesn't cover. Pair the printed value with an `auth_token_hash` you
compute yourself:

```sh
echo "$KEY" | bun run client encrypt
```

## At-rest encryption

`anthropic_api_key` is stored encrypted (AES-256-GCM) when written via the `client`
CLI (`add`/`rotate`/`encrypt`); plaintext rows are still accepted for backward
compatibility.

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
