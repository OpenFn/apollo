-- Instance auth: the allow-list of Lightning clients permitted to call Apollo.
--
-- Instance auth is opt-in via the INSTANCE_AUTH env var. When it is set, the
-- Apollo server gates every /services/* request on a valid bearer token and
-- looks tokens up in this table (via POSTGRES_URL). This table must exist for
-- auth to work — if INSTANCE_AUTH is set but the table is missing, the gate
-- fails closed and rejects every external caller. Without INSTANCE_AUTH, the
-- server stays open as before.
--
-- Rows are managed by hand. Use hash_token.py to mint a token + its hash, then
-- INSERT a row and configure the Lightning instance with the plaintext token as
-- `Authorization: Bearer <token>`. See README.md.

CREATE TABLE IF NOT EXISTS lightning_clients (
    id                SERIAL PRIMARY KEY,
    name              TEXT         UNIQUE NOT NULL,  -- human identifier for the client
    auth_token_hash   VARCHAR(64)  UNIQUE NOT NULL,  -- sha256 hex of the bearer token (never the plaintext)
    anthropic_api_key TEXT                           -- Anthropic key Apollo uses for this client; NULL => global env key
);
