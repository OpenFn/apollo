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
    "version": "4.2.10", // Adaptor version (required)
    "function": "create", // Specific function name (optional)
    "list_only": true, // Return only function names (optional)
    "signatures_only": true // Return only function signatures (optional)
}
```