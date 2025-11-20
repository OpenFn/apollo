import json
import os
from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import execute_values
import sentry_sdk
from util import create_logger, ApolloError, apollo

logger = create_logger("upload_adaptor_docs")


def filter_function_docs(raw_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter and simplify the raw documentation to keep only useful function info.

    Keeps:
    - Functions (kind === "function")
    - External functions (kind === "external-function") - from language-common
    - External exports (kind === "external") - from language-common
    - Public access only

    Removes:
    - typedefs
    - private functions
    - meta, order, level, newscope, customTags, state
    """
    filtered = []

    for item in raw_docs:
        # Include function, external-function, and external kinds
        if item.get("kind") not in ["function", "external-function", "external"]:
            continue
        if item.get("access") == "private":
            continue

        # Get signature - handle both string and array formats
        signature = item.get("signature", "")
        if isinstance(signature, list):
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

        # Optionally include source, version, and common flag if present (for common functions from language-common)
        if item.get("source"):
            function_doc["source"] = item.get("source")
        if item.get("version"):
            function_doc["version"] = item.get("version")
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
    - adaptor_name: e.g., "@openfn/language-dhis2", "@openfn/language-kobotoolbox"
    - version: e.g., "4.2.10"
    - function_name: e.g., "create" or "tracker.import"
    - signature: e.g., "create(path: string, data: DHIS2Data, params: object): Operation"
    - function_data: JSONB containing the full function doc

    This function first deletes all existing rows for the adaptor version,
    then inserts the new data. This ensures we don't have stale functions
    if the docs change.
    """

    # First, delete all existing rows for this adaptor version
    delete_sql = """
    DELETE FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    """

    with conn.cursor() as cur:
        cur.execute(delete_sql, (adaptor_name, version))
        deleted_count = cur.rowcount
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} existing functions for {adaptor_name}@{version}")
        conn.commit()

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

    # Insert new data
    insert_sql = """
    INSERT INTO adaptor_function_docs
        (adaptor_name, version, function_name, signature, function_data)
    VALUES %s
    """

    with conn.cursor() as cur:
        execute_values(cur, insert_sql, rows)
        conn.commit()

    logger.info(f"Uploaded {len(rows)} functions for {adaptor_name}@{version}")


def process_adaptor_docs(adaptor_name: str, version: str, raw_docs: List[Dict[str, Any]], data: dict) -> dict:
    """
    Process and upload a single adaptor's documentation.

    Args:
        adaptor_name: The full adaptor name (e.g., "@openfn/language-kobotoolbox", "@openfn/language-dhis2")
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

    # Upload
    if data.get("DATABASE_URL"):
        db_url = data["DATABASE_URL"]
    else:
        db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        msg = "Missing DATABASE_URL in payload or environment"
        logger.error(msg)
        raise ApolloError(500, msg, type="BAD_REQUEST")

    logger.info("Connecting to PostgreSQL")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise ApolloError(500, f"Database connection failed: {str(e)}", type="DATABASE_ERROR")

    try:
        create_table_if_not_exists(conn)
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


def main(data: dict) -> dict:
    """
    Main entry point for uploading adaptor function docs.

    Expected payload:
    {
        "adaptor": "kobotoolbox" or "@openfn/language-kobotoolbox",
        "version": "4.2.7",
        "DATABASE_URL": "postgresql://..."  # Optional, will use env if not provided
    }

    This will call adaptor_apis service to fetch the docs, then upload them.
    """
    logger.info("Starting upload_adaptor_docs...")

    sentry_sdk.set_context("request_data", {
        k: v for k, v in data.items() if k not in ["DATABASE_URL", "api_key"]
    })

    # Validate required fields
    if "adaptor" not in data:
        raise ApolloError(400, "Missing required field: 'adaptor'", type="BAD_REQUEST")
    if "version" not in data:
        raise ApolloError(400, "Missing required field: 'version'", type="BAD_REQUEST")

    adaptor = data["adaptor"]
    version = data["version"]

    sentry_sdk.set_tag("adaptor", adaptor)
    sentry_sdk.set_tag("version", version)

    if not adaptor.startswith("@openfn/"):
        adaptor_full = f"@openfn/language-{adaptor}"
    else:
        adaptor_full = adaptor

    adaptor_version_string = f"{adaptor_full}@{version}"

    logger.info(f"Fetching docs from adaptor_apis for {adaptor_version_string}")

    try:
        with sentry_sdk.start_span(description="fetch_adaptor_apis"):
            api_result = apollo("adaptor_apis", {"adaptors": [adaptor_version_string]})

        if api_result.get("type") == "SERVICE_ERROR":
            raise ApolloError(
                api_result.get("code", 500),
                api_result.get("message", "Unknown service error"),
                type=api_result.get("type", "ADAPTOR_API_ERROR")
            )

        if api_result.get("errors") and adaptor_version_string in api_result["errors"]:
            msg = f"Failed to fetch docs for {adaptor_version_string}"
            raise ApolloError(500, msg, type="ADAPTOR_API_ERROR")

        if "docs" not in api_result or adaptor_version_string not in api_result["docs"]:
            msg = f"No docs returned for {adaptor_version_string}"
            sentry_sdk.capture_message(msg, level="error")
            raise ApolloError(500, msg, type="ADAPTOR_API_ERROR")

        raw_docs = api_result["docs"][adaptor_version_string]
        logger.info(f"Received {len(raw_docs)} items from adaptor_apis")

        logger.info(f"Processing and uploading docs for {adaptor_full}@{version}")

        with sentry_sdk.start_span(description="process_and_upload_docs"):
            result = process_adaptor_docs(adaptor_full, version, raw_docs, data)

        logger.info(f"✓ Successfully uploaded {result['functions_uploaded']} functions for {adaptor_full}@{version}")
        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.error(f"Error calling adaptor_apis: {str(e)}")
        raise ApolloError(500, f"Failed to fetch docs: {str(e)}", type="ADAPTOR_API_ERROR")