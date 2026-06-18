-- Per-client API key mapping: known clients and the key Apollo uses for each.
--
-- Opt-in purely by provisioning this table (via POSTGRES_URL). When present,
-- Apollo hashes each request's incoming api_key and, on a match, swaps in that
-- client's anthropic_api_key; unrecognised keys pass through unchanged. Without
-- this table, every request passes through as before. See README.md.
--
-- Rows are managed by hand. Use hash_token.py to mint a token + its hash, then
-- INSERT a row and configure the client to send the plaintext token as its
-- api_key (for Lightning, the AI_ASSISTANT_API_KEY env var).

CREATE TABLE IF NOT EXISTS lightning_clients (
    id                SERIAL PRIMARY KEY,
    name              TEXT         UNIQUE NOT NULL,  -- human identifier for the client
    auth_token_hash   VARCHAR(64)  UNIQUE NOT NULL,  -- sha256 hex of the token (never the plaintext)
    anthropic_api_key TEXT                           -- key Apollo uses for this client; NULL => global env key
);
