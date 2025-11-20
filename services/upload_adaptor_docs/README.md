# Upload Adaptor Docs

Service to parse and upload version-specific adaptor function documentation to PostgreSQL.

## Overview

This service processes JSDoc-generated adaptor documentation (raw JSON format) and stores it in PostgreSQL for keyword-based retrieval by `search_adaptor_docs` and `job_chat`.

### What gets filtered:

**Removed:**
- Type definitions (`kind: "typedef"`)
- Private functions (`access: "private"`)
- Internal metadata (`meta`, `order`, `level`, `newscope`, `customTags`, `state`)

**Kept:**
- Public functions (`kind: "function"`, `access: "public"`)
- External/common functions from language-common (`kind: "external-function"` or `"external"`)
- Function name, scope, description
- **Signature** (e.g., `create(path: string, data: DHIS2Data, params: object): Operation`)
- Parameters (name, type, description, optional flag)
- Examples
- Return types

## Database Schema

The service automatically creates this table if it doesn't exist:

```sql
CREATE TABLE adaptor_function_docs (
    id SERIAL PRIMARY KEY,
    adaptor_name VARCHAR(255) NOT NULL,      -- e.g., "@openfn/language-dhis2", "@openfn/language-kobotoolbox"
    version VARCHAR(50) NOT NULL,             -- e.g., "4.2.10"
    function_name VARCHAR(255) NOT NULL,      -- e.g., "create" or "tracker.import"
    signature TEXT NOT NULL,                  -- e.g., "create(path: string, data: DHIS2Data, params: object): Operation"
    function_data JSONB NOT NULL,             -- Full function documentation
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(adaptor_name, version, function_name)
);

CREATE INDEX IF NOT EXISTS idx_adaptor_name_version
    ON adaptor_function_docs(adaptor_name, version);
CREATE INDEX IF NOT EXISTS idx_function_name
    ON adaptor_function_docs(function_name);
CREATE INDEX IF NOT EXISTS idx_signature
    ON adaptor_function_docs USING gin(to_tsvector('english', signature));
```

## Usage

Provide just the adaptor name and version. The service will automatically call the `adaptor_apis` service to fetch the docs.

**Payload:**
```json
{
  "adaptor": "kobotoolbox",
  "version": "4.2.7"
}
```

You can also use the full adaptor name:
```json
{
  "adaptor": "@openfn/language-kobotoolbox",
  "version": "4.2.7"
}
```

**Via entry.py:**
```bash
python -m services.entry upload_adaptor_docs -i services/upload_adaptor_docs/tmp/test_upload_simple.json
```

**Via HTTP (requires running server):**
```bash
curl -X POST http://localhost:3000/services/upload_adaptor_docs \
  -H "Content-Type: application/json" \
  -d '{"adaptor": "kobotoolbox", "version": "4.2.7"}'
```

**Response:**
```json
{
  "success": true,
  "adaptor": "@openfn/language-kobotoolbox",
  "version": "4.2.7",
  "functions_uploaded": 7,
  "function_list": [
    "getDeploymentInfo",
    "getForms",
    "getSubmissions",
    "http.get",
    "http.post",
    "http.put",
    "http.request"
  ]
}
```

## Payload Schema

**Required:**
- **`adaptor`** (string): Adaptor name - accepts either:
  - Short form: `"kobotoolbox"`, `"dhis2"`, etc.
  - Full form: `"@openfn/language-kobotoolbox"`, `"@openfn/language-dhis2"`, etc.
- **`version`** (string): Adaptor version (e.g., `"4.2.7"`)

**Optional:**
- **`DATABASE_URL`** (string): PostgreSQL connection string (falls back to environment variable)

The service will:
1. Call `adaptor_apis` service to fetch the latest docs
2. Filter and process the docs
3. Delete any existing functions for this adaptor@version
4. Upload new functions to PostgreSQL

## Integration with Other Services

### search_adaptor_docs

The `search_adaptor_docs` service queries this database to retrieve function documentation by:
- Adaptor name and version
- Function name (keyword search)
- Signature content (full-text search)

### job_chat

The `job_chat` service uses function signatures to:
1. Show available functions in the system prompt
2. Fetch specific function docs and examples when referenced
3. Provide context-aware code suggestions

## Example Queries

### Get all functions for an adaptor version

```python
import psycopg2
import os

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

cur.execute("""
    SELECT function_name, signature
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
""", ("@openfn/language-dhis2", "4.2.10"))

for row in cur.fetchall():
    print(f"{row[0]}: {row[1]}")
```

### Get specific function with examples

```python
cur.execute("""
    SELECT function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s
      AND version = %s
      AND function_name = %s
""", ("@openfn/language-dhis2", "4.2.10", "create"))

doc = cur.fetchone()[0]
print(doc['description'])
print('\n'.join(doc['examples']))
```

### Search functions by signature content

```python
cur.execute("""
    SELECT function_name, signature
    FROM adaptor_function_docs
    WHERE adaptor_name = %s
      AND version = %s
      AND to_tsvector('english', signature) @@ to_tsquery('english', %s)
""", ("@openfn/language-dhis2", "4.2.10", "string & Operation"))
```

## File Structure

```
services/upload_adaptor_docs/
├── upload_adaptor_docs.py    # Main service
├── README.md                 # This file
└── schema.sql                # Database schema (for reference)
```

## Notes

- **Replace behavior**: Re-uploading the same adaptor/version **deletes all existing functions** for that version first, then inserts the new data. This ensures no stale functions remain if the docs change.
- **Idempotent**: Safe to run multiple times with the same data
- **Scope handling**: Functions are stored with scope prefix (e.g., `util.attr`, `tracker.import`) or just name for global scope
- **No vector search**: Designed for keyword and full-text search only
- **Automatic table creation**: Creates `adaptor_function_docs` table if it doesn't exist
- **Adaptor name normalization**: Adaptor names are stored with the full `@openfn/language-` prefix (e.g., `"@openfn/language-kobotoolbox"` not `"kobotoolbox"`)
