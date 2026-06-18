-- Instance auth: the allow-list of Lightning clients permitted to call Apollo.
--
-- Instance auth is opt-in via the INSTANCE_AUTH env var. When it is set, the
-- Apollo server gates every /services/* request on the api_key the caller sends
-- in the request body, looking its hash up in this table (via POSTGRES_URL).
-- This table must exist for auth to work — if INSTANCE_AUTH is set but the table
-- is missing, the gate fails closed and rejects every external caller. Without
-- INSTANCE_AUTH, the server stays open as before.
--
-- Rows are managed by hand. Use hash_token.py to hash a client's api_key, then
-- INSERT a row. The inbound api_key is only a credential; Apollo never forwards
-- it to the LLM, using anthropic_api_key (below) instead. See README.md.

CREATE TABLE IF NOT EXISTS lightning_clients (
    id                SERIAL PRIMARY KEY,
    name              TEXT         UNIQUE NOT NULL,  -- human identifier for the client
    auth_token_hash   VARCHAR(64)  UNIQUE NOT NULL,  -- sha256 hex of the client's api_key credential (never the plaintext)
    anthropic_api_key TEXT                           -- Anthropic key Apollo uses for this client; NULL => global env key
);
