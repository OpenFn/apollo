## Search Adaptor Docs

This service retrieves adaptor function documentation from PostgreSQL for a specific adaptor version.

## Usage

The service requires a `DATABASE_URL` environment variable to connect to PostgreSQL.

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
    "adaptor": "@openfn/language-dhis2", // Adaptor name (required)
    "version": "4.2.10" | "latest", // Adaptor version (optional, defaults to "latest")
    "query_type": "list" | "signatures" | "function" | "all", // Query type (required)
    "function_name": "create", // Specific function name (required if query_type is "function")
    "format": "json" | "natural_language", // Output format (optional, defaults to "json")
    "DATABASE_URL": "postgresql://..." // Database connection string (optional, falls back to environment variable)
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

### Version Resolution

The `version` field is **optional** and defaults to `"latest"` if not provided. You can also explicitly use `"latest"` or `"@latest"` as the version to automatically resolve to the most recently uploaded version for that adaptor:

```json
{
    "adaptor": "@openfn/language-dhis2",
    "query_type": "list"
}
```

Or explicitly:

```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "latest",
    "query_type": "list"
}
```

Both will query the database for the most recent version based on the `created_at` timestamp.

### Examples

**Get list of function names:**
```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "4.2.10",
    "query_type": "list"
}
```

**Get function signatures:**
```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "4.2.10",
    "query_type": "signatures"
}
```

**Get specific function in JSON format:**
```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "4.2.10",
    "query_type": "function",
    "function_name": "create"
}
```

**Get specific function in natural language format:**
```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "4.2.10",
    "query_type": "function",
    "function_name": "create",
    "format": "natural_language"
}
```

**Get all functions in natural language format:**
```json
{
    "adaptor": "@openfn/language-dhis2",
    "version": "4.2.10",
    "query_type": "all",
    "format": "natural_language"
}
```