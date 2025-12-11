import time
from typing import Dict, List, Any
import sentry_sdk
from util import create_logger, ApolloError, AdaptorSpecifier, get_db_connection
from load_adaptor_docs.load_adaptor_docs import load_adaptor_docs

logger = create_logger("search_adaptor_docs")


def ensure_docs_loaded(adaptor: AdaptorSpecifier, conn, skip_if_exists: bool = True) -> None:
    """
    Ensure adaptor documentation is loaded into the database.

    Args:
        adaptor: The adaptor specifier
        conn: Database connection to reuse
        skip_if_exists: If True, skip loading if docs already exist
    """
    try:
        logger.info(f"Checking/loading adaptor docs for {adaptor.specifier}")
        start_time = time.time()
        load_result = load_adaptor_docs(
            adaptor=adaptor.specifier,
            skip_if_exists=skip_if_exists,
            conn=conn
        )
        duration = time.time() - start_time

        if load_result.get("skipped"):
            logger.info(f"Adaptor docs for {adaptor.specifier} already exist (checked in {duration:.3f}s)")
        elif load_result.get("success"):
            logger.info(f"Successfully loaded {load_result.get('functions_uploaded', 0)} functions for {adaptor.specifier} in {duration:.3f}s")
        else:
            logger.warning(f"Failed to load adaptor docs for {adaptor.specifier} after {duration:.3f}s")
    except Exception as e:
        duration = time.time() - start_time if 'start_time' in locals() else 0
        logger.warning(f"Failed to load adaptor docs after {duration:.3f}s: {str(e)}")
        sentry_sdk.capture_exception(e)


def fetch_function_list(adaptor: AdaptorSpecifier, conn, auto_load: bool = False) -> list:
    """Fetch just the list of function names."""
    if auto_load:
        ensure_docs_loaded(adaptor, conn)

    query = """
    SELECT function_name
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor.name, adaptor.version))
        rows = cur.fetchall()
        return [row[0] for row in rows]


def fetch_signatures(adaptor: AdaptorSpecifier, conn, auto_load: bool = False) -> dict:
    """Fetch function names with their signatures."""
    if auto_load:
        ensure_docs_loaded(adaptor, conn)

    query = """
    SELECT function_name, signature
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor.name, adaptor.version))
        rows = cur.fetchall()
        result = {row[0]: row[1] for row in rows}

    return result


def json_to_natural_language(func_data: dict, adaptor: AdaptorSpecifier = None) -> str:
    """
    Convert function JSON to natural language format for LLM consumption.
    """
    name = func_data.get("name", "")
    scope = func_data.get("scope", "global")
    function_name = name if scope == "global" else f"{scope}.{name}"

    nl = f"Function: {function_name}\n"

    if adaptor:
        nl += f"Adaptor: {adaptor.name}\n"
        nl += f"Version: {adaptor.version}\n"

    nl += "\n"

    # Signature
    signature = func_data.get("signature", "")
    if signature:
        nl += f"Signature: {signature}\n\n"

    # Description
    description = func_data.get("description", "")
    if description:
        nl += f"Description: {description}\n\n"

    # Parameters
    params = func_data.get("params", [])
    if params:
        nl += "Parameters:\n"
        for param in params:
            param_name = param.get("name", "")
            param_types = param.get("type", [])
            param_type = ", ".join(param_types) if param_types else "any"
            param_desc = param.get("description", "")
            optional = " (optional)" if param.get("optional") else ""
            nl += f"- {param_name} ({param_type}){optional}: {param_desc}\n"
        nl += "\n"

    # Returns
    returns = func_data.get("returns", [])
    if returns:
        return_types = []
        for ret in returns:
            ret_types = ret.get("type", [])
            return_types.extend(ret_types)
        if return_types:
            nl += f"Returns: {', '.join(return_types)}\n\n"

    # Examples
    examples = func_data.get("examples", [])
    if examples:
        nl += "Examples:\n\n"
        for i, example in enumerate(examples, 1):
            nl += f"Example {i}:\n{example}\n\n"

    return nl.strip()


def fetch_single_function(adaptor: AdaptorSpecifier, function_name: str, conn, format: str = "json", auto_load: bool = False) -> dict | str:
    """
    Fetch a specific function's documentation.

    Args:
        format: "json" or "natural_language"
        auto_load: If True, automatically load adaptor docs if not present
    """
    if auto_load:
        ensure_docs_loaded(adaptor, conn)

    query = """
    SELECT function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s AND function_name = %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor.name, adaptor.version, function_name))
        row = cur.fetchone()
        if row:
            func_data = row[0]  # JSONB data
            if format == "natural_language":
                return json_to_natural_language(func_data, adaptor)
            return func_data
        return None


def fetch_all_functions(adaptor: AdaptorSpecifier, conn, format: str = "json", auto_load: bool = False) -> list:
    """
    Fetch all function documentation for an adaptor version.

    Args:
        format: "json" or "natural_language"
        auto_load: If True, automatically load adaptor docs if not present
    """
    if auto_load:
        ensure_docs_loaded(adaptor, conn)

    query = """
    SELECT function_name, function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor.name, adaptor.version))
        rows = cur.fetchall()

        if format == "natural_language":
            return [
                {
                    "function_name": row[0],
                    "text": json_to_natural_language(row[1], adaptor)
                }
                for row in rows
            ]

        return [{"function_name": row[0], "data": row[1]} for row in rows]


def main(data: dict) -> dict:
    """
    Main entry point for searching adaptor function docs.

    Expected payload:
    {
        "adaptor": "@openfn/language-dhis2@4.2.10",  # Can also be "dhis2@4.2.10"
        "query_type": "list" | "signatures" | "function" | "all",
        "function_name": "create",  # Required if query_type is "function"
        "format": "json" | "natural_language"  # Optional, defaults to "json"
    }
    """
    logger.info("Starting search_adaptor_docs...")

    sentry_sdk.set_context("request_data", data)

    # Validate required fields
    if "adaptor" not in data:
        raise ApolloError(400, "Missing required field: 'adaptor'", type="BAD_REQUEST")
    if "query_type" not in data:
        raise ApolloError(400, "Missing required field: 'query_type'", type="BAD_REQUEST")

    adaptor_input = data["adaptor"]
    query_type = data["query_type"]
    function_name = data.get("function_name")
    format = data.get("format", "json")

    # Parse the adaptor string
    adaptor = AdaptorSpecifier(adaptor_input)

    sentry_sdk.set_tag("adaptor", adaptor.name)
    sentry_sdk.set_tag("version", adaptor.version)
    sentry_sdk.set_tag("query_type", query_type)

    # Validate query_type
    valid_types = ["list", "signatures", "function", "all"]
    if query_type not in valid_types:
        raise ApolloError(400, f"Invalid query_type. Must be one of: {', '.join(valid_types)}", type="BAD_REQUEST")

    if query_type == "function" and not function_name:
        raise ApolloError(400, "Missing required field: 'function_name' for query_type='function'", type="BAD_REQUEST")

    # Connect to PostgreSQL
    conn = get_db_connection()

    try:
        logger.info(f"Querying {adaptor.specifier} (type: {query_type}, format: {format})")

        # Execute queries
        if query_type == "list":
            # Return list of function names
            functions = fetch_function_list(adaptor, conn)
            logger.info(f"Found {len(functions)} functions")
            return {
                "adaptor": adaptor.name,
                "version": adaptor.version,
                "query_type": "list",
                "functions": functions
            }

        elif query_type == "signatures":
            # Return function names with signatures
            signatures = fetch_signatures(adaptor, conn)
            logger.info(f"Found {len(signatures)} function signatures")
            return {
                "adaptor": adaptor.name,
                "version": adaptor.version,
                "query_type": "signatures",
                "signatures": signatures
            }

        elif query_type == "function":
            # Fetch a specific function
            logger.info(f"Fetching function: {function_name}")
            func_data = fetch_single_function(adaptor, function_name, conn, format)
            if not func_data:
                raise ApolloError(404, f"Function '{function_name}' not found", type="NOT_FOUND")

            return {
                "adaptor": adaptor.name,
                "version": adaptor.version,
                "query_type": "function",
                "function_name": function_name,
                "format": format,
                "data": func_data
            }

        elif query_type == "all":
            # Fetch all functions
            functions = fetch_all_functions(adaptor, conn, format)
            logger.info(f"Found {len(functions)} functions")
            return {
                "adaptor": adaptor.name,
                "version": adaptor.version,
                "query_type": "all",
                "format": format,
                "count": len(functions),
                "functions": functions
            }

    except ApolloError:
        raise
    except Exception as e:
        logger.error(f"Error querying database: {str(e)}")
        raise ApolloError(500, f"Query failed: {str(e)}", type="DATABASE_ERROR")
    finally:
        conn.close()

