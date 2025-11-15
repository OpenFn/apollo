## Adaptor APIS

Service to provide a JSON representation of any adaptor APIs

Will download and parse adaptor source to generate JSON documentation

Uses a local file cache but does not currently use a database cache or touch the
database at all

Designed for use in the short-term by the new adaptor doc search features. In
the longer term this is likely to be used by Lightning directly to drive in-app
documentation.

Payload

```json
{
  "adaptors": ["kobotoolbox@4.2.7", "asana@5.0.6"]
}
```

Returns:

```json
{
  "docs": {
    "kobotoolbox@4.2.7": [ ... ],
    "asana@5.0.6": [ ... ]
  },
  "errors": [/*name of any adaptor that fails*/]
}
```

## Usage

This service can be called from any apollo module

```py
result = apollo("adaptor_apis", { "adaptors": ["kobotoolbox@4.2.7"] })
```
