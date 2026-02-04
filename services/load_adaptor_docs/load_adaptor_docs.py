import json
import time
from typing import Dict, List, Any
from psycopg2.extras import execute_values
import sentry_sdk
from util import create_logger, ApolloError, apollo, AdaptorSpecifier, get_db_connection

logger = create_logger("load_adaptor_docs")


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


def check_existing_docs(adaptor: AdaptorSpecifier, conn) -> dict:
    """
    Check if docs already exist for this adaptor+version and return their metadata.

    Returns:
        Dictionary with exists flag and function list, or None if not found
    """
    check_sql = """
    SELECT function_name, signature
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(check_sql, (adaptor.name, adaptor.version))
        rows = cur.fetchall()

        if rows:
            function_list = [row[0] for row in rows]
            logger.info(f"✓ Docs already exist for {adaptor.specifier} ({len(rows)} functions)")
            return {
                "exists": True,
                "function_count": len(rows),
                "function_list": function_list
            }

        logger.info(f"No existing docs found for {adaptor.specifier}")
        return {"exists": False}


def upload_to_postgres(
    adaptor: AdaptorSpecifier,
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
        cur.execute(delete_sql, (adaptor.name, adaptor.version))
        conn.commit()

    # Prepare data for insertion
    rows = []
    for func in filtered_docs:
        scope = func.get("scope", "global")
        name = func.get("name")
        function_name = name if scope == "global" else f"{scope}.{name}"
        signature = func.get("signature", "")

        rows.append((
            adaptor.name,
            adaptor.version,
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


def process_adaptor_docs(adaptor: AdaptorSpecifier, raw_docs: List[Dict[str, Any]], conn=None) -> dict:
    """
    Process and upload a single adaptor's documentation.

    Args:
        adaptor: AdaptorSpecifier object containing name and version
        raw_docs: Array of raw documentation objects
        conn: Optional database connection to reuse. If None, creates a new connection.

    Returns:
        Dictionary with success status and upload details
    """
    # Filter and simplify
    filtered_docs = filter_function_docs(raw_docs)

    # Extract function list
    function_list = extract_function_list(filtered_docs)

    # Upload
    should_close_conn = conn is None
    if conn is None:
        conn = get_db_connection()

    try:
        upload_to_postgres(adaptor, filtered_docs, conn)

        return {
            "success": True,
            "adaptor": adaptor.name,
            "version": adaptor.version,
            "functions_uploaded": len(filtered_docs),
            "function_list": function_list
        }

    except Exception as e:
        logger.error(f"Error uploading to database: {str(e)}")
        raise ApolloError(500, f"Upload failed: {str(e)}", type="DATABASE_ERROR")
    finally:
        if should_close_conn:
            conn.close()


def load_adaptor_docs(adaptor: str, skip_if_exists: bool = True, conn=None) -> dict:
    """
    Load adaptor documentation into the database.

    Args:
        adaptor: Adaptor string like "@openfn/language-http@3.1.11" or "http@3.1.11"
        skip_if_exists: If True, skip if docs already exist in database
        conn: Optional database connection to reuse. If None, creates a new connection.

    Returns:
        Dictionary with success status and upload details
    """
    adaptor_spec = AdaptorSpecifier(adaptor)

    sentry_sdk.set_tag("adaptor", adaptor_spec.name)
    sentry_sdk.set_tag("version", adaptor_spec.version)

    # Ensure we have a connection and create table if needed
    should_close_conn = conn is None
    if conn is None:
        conn = get_db_connection()

    try:
        create_table_if_not_exists(conn)

        # Check if docs already exist (if skip_if_exists is enabled)
        if skip_if_exists:
            logger.info("Checking if docs already exist in database")
            existing_check = check_existing_docs(adaptor_spec, conn)

            if existing_check["exists"]:
                return {
                    "success": True,
                    "adaptor": adaptor_spec.name,
                    "version": adaptor_spec.version,
                    "skipped": True,
                    "functions_uploaded": existing_check["function_count"],
                    "function_list": existing_check["function_list"]
                }
        with sentry_sdk.start_span(description="fetch_adaptor_apis"):
            api_result = apollo("adaptor_apis", {"adaptors": [adaptor_spec.specifier]})

        if api_result.get("type") == "SERVICE_ERROR":
            raise ApolloError(
                api_result.get("code", 500),
                api_result.get("message", "Unknown service error"),
                type=api_result.get("type", "ADAPTOR_API_ERROR")
            )

        if api_result.get("errors") and adaptor_spec.specifier in api_result["errors"]:
            msg = f"Failed to fetch docs for {adaptor_spec.specifier}"
            raise ApolloError(500, msg, type="ADAPTOR_API_ERROR")

        if "docs" not in api_result or adaptor_spec.specifier not in api_result["docs"]:
            msg = f"No docs returned for {adaptor_spec.specifier}"
            sentry_sdk.capture_message(msg, level="error")
            raise ApolloError(500, msg, type="ADAPTOR_API_ERROR")

        raw_docs = api_result["docs"][adaptor_spec.specifier]

        with sentry_sdk.start_span(description="process_and_upload_docs"):
            result = process_adaptor_docs(adaptor_spec, raw_docs, conn=conn)

        return result

    except ApolloError:
        raise
    except Exception as e:
        logger.error(f"Error calling adaptor_apis: {str(e)}")
        raise ApolloError(500, f"Failed to fetch docs: {str(e)}", type="ADAPTOR_API_ERROR")
    finally:
        if should_close_conn:
            conn.close()


def main(data: dict) -> dict:
    """
    Main entry point for uploading adaptor function docs when called as a service.

    Expected payload:
    {
        "adaptor": "@openfn/language-http@3.1.11",  # Can also be "http@3.1.11"
        "skip_if_exists": true  # Optional, defaults to true
    }

    This will call adaptor_apis service to fetch the docs, then upload them.
    If skip_if_exists is true and docs already exist, it returns existing data without reprocessing.
    """
    logger.info("Starting load_adaptor_docs service...")

    sentry_sdk.set_context("request_data", {
        k: v for k, v in data.items() if k not in ["api_key"]
    })

    # Validate required fields
    if "adaptor" not in data:
        raise ApolloError(400, "Missing required field: 'adaptor'", type="BAD_REQUEST")

    return load_adaptor_docs(
        adaptor=data["adaptor"],
        skip_if_exists=data.get("skip_if_exists", True)
    )