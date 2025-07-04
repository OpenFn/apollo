# latest_adaptors Service

This service fetches the latest adaptor information from the OpenFn adaptors repository.

## Usage

Run the service directly:

```bash
poetry run python services/latest_adaptors/latest_adaptors.py
```

## What it does

- Fetches all adaptor package names from the OpenFn/adaptors GitHub repository
- Retrieves package.json files for each adaptor to get description, label, and version
- Returns a dictionary mapping adaptor names to their metadata

## Output

Returns a dictionary where keys are adaptor names and values contain:
- `description`: Package description
- `label`: Human-readable label
- `version`: Current version

Example:
```json
{
  "language-common": {
    "description": "Common operations for OpenFn",
    "label": "Common",
    "version": "1.0.0"
  }
}
```