import json
import os
from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import execute_values
from util import create_logger, ApolloError

logger = create_logger("upload_adaptor_docs")


def filter_function_docs(raw_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter and simplify the raw documentation to keep only useful function info.

    Keeps:
    - Functions (kind === "function")
    - Public access only

    Removes:
    - typedefs
    - external-function / external (common functions)
    - private functions
    - meta, order, level, newscope, customTags, state
    """
    filtered = []

    for item in raw_docs:
        if item.get("kind") != "function":
            continue
        if item.get("access") == "private":
            continue

        # Get signature - handle both string and array formats
        signature = item.get("signature", "")
        if isinstance(signature, list):
            # New format: array of signatures, take the first one
            signature = signature[0] if signature else ""

        # Build simplified function doc
        function_doc = {
            "name": item.get("name"),
            "scope": item.get("scope", "global"),
            "signature": signature,
            "description": item.get("description", ""),
            "params": item.get("params", []),
            "examples": item.get("examples", []),
            "returns": item.get("returns", [])
        }

        # Optionally include source and common flag if present (for common functions from language-common)
        if item.get("source"):
            function_doc["source"] = item.get("source")
        if item.get("common"):
            function_doc["common"] = True

        # Clean up params - keep only essential fields
        cleaned_params = []
        for param in function_doc["params"]:
            cleaned_param = {
                "name": param.get("name"),
                "type": param.get("type", {}).get("names", []),
                "description": param.get("description", ""),
            }
            if param.get("optional"):
                cleaned_param["optional"] = True
            cleaned_params.append(cleaned_param)
        function_doc["params"] = cleaned_params

        # Clean up returns - keep only type names
        cleaned_returns = []
        for ret in function_doc["returns"]:
            cleaned_returns.append({
                "type": ret.get("type", {}).get("names", [])
            })
        function_doc["returns"] = cleaned_returns

        filtered.append(function_doc)

    return filtered


def extract_function_list(filtered_docs: List[Dict[str, Any]]) -> List[str]:
    """
    Extract a simple list of function names with their scope.

    Returns:
        ["create", "destroy", "get", "update", "util.attr", "tracker.import", ...]
    """
    function_list = []
    for func in filtered_docs:
        scope = func.get("scope", "global")
        name = func.get("name")
        if scope == "global":
            function_list.append(name)
        else:
            function_list.append(f"{scope}.{name}")
    return function_list


def create_table_if_not_exists(conn):
    """Create the adaptor_function_docs table if it doesn't exist."""
    create_table_sql = """
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

    CREATE INDEX IF NOT EXISTS idx_adaptor_name_version
        ON adaptor_function_docs(adaptor_name, version);
    CREATE INDEX IF NOT EXISTS idx_function_name
        ON adaptor_function_docs(function_name);
    CREATE INDEX IF NOT EXISTS idx_signature
        ON adaptor_function_docs USING gin(to_tsvector('english', signature));
    """

    with conn.cursor() as cur:
        cur.execute(create_table_sql)
        conn.commit()
    logger.info("Table adaptor_function_docs ready")


def upload_to_postgres(
    adaptor_name: str,
    version: str,
    filtered_docs: List[Dict[str, Any]],
    conn
):
    """
    Upload filtered function docs to PostgreSQL.

    Each function becomes a separate row:
    - adaptor_name: e.g., "@openfn/language-dhis2"
    - version: e.g., "4.2.10"
    - function_name: e.g., "create" or "tracker.import"
    - signature: e.g., "create(path: string, data: DHIS2Data, params: object): Operation"
    - function_data: JSONB containing the full function doc
    """

    # Prepare data for insertion
    rows = []
    for func in filtered_docs:
        scope = func.get("scope", "global")
        name = func.get("name")
        function_name = name if scope == "global" else f"{scope}.{name}"
        signature = func.get("signature", "")

        rows.append((
            adaptor_name,
            version,
            function_name,
            signature,
            json.dumps(func)
        ))

    # Insert or update
    insert_sql = """
    INSERT INTO adaptor_function_docs
        (adaptor_name, version, function_name, signature, function_data)
    VALUES %s
    ON CONFLICT (adaptor_name, version, function_name)
    DO UPDATE SET
        signature = EXCLUDED.signature,
        function_data = EXCLUDED.function_data,
        updated_at = CURRENT_TIMESTAMP
    """

    with conn.cursor() as cur:
        execute_values(cur, insert_sql, rows)
        conn.commit()

    logger.info(f"Uploaded {len(rows)} functions for {adaptor_name}@{version}")


def main(data: dict) -> dict:
    """
    Main entry point for uploading adaptor function docs.

    Expected payload (Format 1 - Legacy):
    {
        "adaptor": "@openfn/language-dhis2",
        "version": "4.2.10",
        "raw_docs": [...],  # Array of function docs from JSDoc
        "DATABASE_URL": "postgresql://..."  # Optional, will use env if not provided
    }

    Expected payload (Format 2 - New):
    {
        "docs": {
            "kobotoolbox@4.2.7": [...]
        },
        "errors": [],
        "DATABASE_URL": "postgresql://..."  # Optional, will use env if not provided
    }
    """
    logger.info("Starting upload_adaptor_docs...")

    # Detect format and extract data
    if "docs" in data:
        # New format with nested structure
        docs_dict = data["docs"]
        errors = data.get("errors", [])

        if errors:
            logger.warning(f"Found {len(errors)} errors in payload: {errors}")

        if not docs_dict:
            raise ApolloError(400, "No adaptor docs found in 'docs' object", type="BAD_REQUEST")

        # Process each adaptor in the docs object
        results = []
        for adaptor_version_key, raw_docs in docs_dict.items():
            # Parse adaptor name and version from key like "kobotoolbox@4.2.7"
            if "@" not in adaptor_version_key:
                raise ApolloError(
                    400,
                    f"Invalid adaptor key format: '{adaptor_version_key}'. Expected format: 'adaptorName@version'",
                    type="BAD_REQUEST"
                )

            adaptor_name, version = adaptor_version_key.rsplit("@", 1)

            logger.info(f"Processing {adaptor_name}@{version}")
            logger.info(f"Loaded {len(raw_docs)} items")

            result = process_adaptor_docs(adaptor_name, version, raw_docs, data)
            results.append(result)

        # Return combined results
        if len(results) == 1:
            return results[0]
        else:
            return {
                "success": True,
                "adaptors_processed": len(results),
                "results": results
            }

    else:
        # Legacy format with direct fields
        if "adaptor" not in data:
            raise ApolloError(400, "Missing required field: 'adaptor'", type="BAD_REQUEST")
        if "version" not in data:
            raise ApolloError(400, "Missing required field: 'version'", type="BAD_REQUEST")
        if "raw_docs" not in data:
            raise ApolloError(400, "Missing required field: 'raw_docs'", type="BAD_REQUEST")

        adaptor_name = data["adaptor"]
        version = data["version"]
        raw_docs = data["raw_docs"]

        logger.info(f"Processing {adaptor_name}@{version}")
        logger.info(f"Loaded {len(raw_docs)} items")

        return process_adaptor_docs(adaptor_name, version, raw_docs, data)


def process_adaptor_docs(adaptor_name: str, version: str, raw_docs: List[Dict[str, Any]], data: dict) -> dict:
    """
    Process and upload a single adaptor's documentation.

    Args:
        adaptor_name: The adaptor name (e.g., "kobotoolbox" or "@openfn/language-dhis2")
        version: The version string (e.g., "4.2.7")
        raw_docs: Array of raw documentation objects
        data: The original payload (for extracting DATABASE_URL)

    Returns:
        Dictionary with success status and upload details
    """
    # Filter and simplify
    filtered_docs = filter_function_docs(raw_docs)
    logger.info(f"Filtered to {len(filtered_docs)} functions")

    # Extract function list
    function_list = extract_function_list(filtered_docs)
    logger.info(f"Functions: {', '.join(function_list)}")

    # Get database URL
    if data.get("DATABASE_URL"):
        db_url = data["DATABASE_URL"]
    else:
        db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        msg = "Missing DATABASE_URL in payload or environment"
        logger.error(msg)
        raise ApolloError(500, msg, type="BAD_REQUEST")

    # Connect to PostgreSQL
    logger.info("Connecting to PostgreSQL")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise ApolloError(500, f"Database connection failed: {str(e)}", type="DATABASE_ERROR")

    try:
        # Create table if needed
        create_table_if_not_exists(conn)

        # Upload
        upload_to_postgres(adaptor_name, version, filtered_docs, conn)

        logger.info("✓ Upload complete")

        return {
            "success": True,
            "adaptor": adaptor_name,
            "version": version,
            "functions_uploaded": len(filtered_docs),
            "function_list": function_list
        }

    except Exception as e:
        logger.error(f"Error uploading to database: {str(e)}")
        raise ApolloError(500, f"Upload failed: {str(e)}", type="DATABASE_ERROR")
    finally:
        conn.close()
