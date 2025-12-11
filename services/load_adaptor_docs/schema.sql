-- Schema for adaptor function documentation storage
-- Note: This table is automatically created by embed_adaptor_docs service
-- See README.md for example queries

CREATE TABLE IF NOT EXISTS adaptor_function_docs (
    id SERIAL PRIMARY KEY,
    adaptor_name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    function_name VARCHAR(255) NOT NULL,
    signature TEXT NOT NULL,
    function_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(adaptor_name, version, function_name)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_adaptor_name_version
    ON adaptor_function_docs(adaptor_name, version);

CREATE INDEX IF NOT EXISTS idx_function_name
    ON adaptor_function_docs(function_name);

-- Full-text search on signature (for finding functions by parameter types)
CREATE INDEX IF NOT EXISTS idx_signature
    ON adaptor_function_docs USING gin(to_tsvector('english', signature));
