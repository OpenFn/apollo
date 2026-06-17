-- Instance auth: the allow-list of Lightning clients permitted to call Apollo.
--
-- Creating this table is the opt-in for instance auth. When it exists (and
-- POSTGRES_URL is set), the Apollo server gates every /services/* request on a
-- valid bearer token. Without it, the server stays open as before.
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
