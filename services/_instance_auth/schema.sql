-- Instance auth allow-list of Lightning clients permitted to call Apollo. Opt-in
-- via INSTANCE_AUTH; when set, /services/* requests are gated on the api_key the
-- caller sends, looked up here by hash. Rows are managed by hand. See README.md.

CREATE TABLE IF NOT EXISTS lightning_clients (
    id                SERIAL PRIMARY KEY,
    name              TEXT         UNIQUE NOT NULL,  -- human identifier for the client
    auth_token_hash   VARCHAR(64)  UNIQUE NOT NULL,  -- sha256 hex of the client's api_key credential (never the plaintext)
    anthropic_api_key TEXT                           -- Anthropic key Apollo uses for this client; NULL => global env key.
                                                     -- Plaintext, OR an "enc:v1:..." value from encrypt_key.ts when
                                                     -- APOLLO_ENC_KEY is set (see README.md). Both are accepted.
);
