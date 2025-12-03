## Search Adaptor Docs

This service retrieves adaptor function documentation from PostgreSQL for a specific adaptor version.

## Usage

The service requires a `POSTGRES_URL` environment variable to connect to PostgreSQL.

### With the CLI, returning to stdout:

```bash
openfn apollo search_adaptor_docs tmp/payload.json
```

To run directly from this repo (note that the server must be started):

```bash
bun py search_adaptor_docs tmp/payload.json -O
```

## Implementation

The service queries the `adaptor_function_docs` PostgreSQL table to retrieve function documentation, signatures, or function lists for a specific adaptor and version.

## Payload Reference

The input payload is a JSON object with the following structure:

```js
{
    "adaptor": "@openfn/language-dhis2@4.2.10", // Adaptor name with version (required) - can also use short form "dhis2@4.2.10"
    "query_type": "list" | "signatures" | "function" | "all", // Query type (required)
    "function_name": "create", // Specific function name (required if query_type is "function")
    "format": "json" | "natural_language", // Output format (optional, defaults to "json")
    "POSTGRES_URL": "postgresql://..." // Database connection string (optional, falls back to environment variable)
}
```

### Query Types

- **`list`**: Returns only function names
- **`signatures`**: Returns function names with their signatures
- **`function`**: Returns full documentation for a specific function (requires `function_name`)
- **`all`**: Returns full documentation for all functions

### Format Options

- **`json`**: Returns structured JSON data (default)
- **`natural_language`**: Returns human-readable text format, suitable for LLM consumption

### Adaptor String Format

The `adaptor` field accepts the following formats:
- **Full form with version**: `"@openfn/language-dhis2@4.2.10"`
- **Short form with version**: `"dhis2@4.2.10"`

The version **must** be included in the adaptor string. If the version is missing, the service will return a `400 BAD_REQUEST` error with a helpful message.

### Examples

**Get list of function names:**
```json
{
    "adaptor": "@openfn/language-dhis2@4.2.10",
    "query_type": "list"
}
```

**Get function signatures (short form):**
```json
{
    "adaptor": "dhis2@4.2.10",
    "query_type": "signatures"
}
```

**Get specific function in JSON format:**
```json
{
    "adaptor": "@openfn/language-dhis2@4.2.10",
    "query_type": "function",
    "function_name": "create"
}
```

**Get specific function in natural language format:**
```json
{
    "adaptor": "@openfn/language-dhis2@4.2.10",
    "query_type": "function",
    "function_name": "create",
    "format": "natural_language"
}
```

**Get all functions in natural language format:**
```json
{
    "adaptor": "@openfn/language-dhis2@4.2.10",
    "query_type": "all",
    "format": "natural_language"
}
```