import os
from typing import Dict, List, Any
import psycopg2
from util import create_logger, ApolloError

logger = create_logger("search_adaptor_docs")


def fetch_function_list(adaptor_name: str, version: str, conn) -> list:
    """Fetch just the list of function names."""
    query = """
    SELECT function_name
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version))
        rows = cur.fetchall()
        return [row[0] for row in rows]


def fetch_signatures(adaptor_name: str, version: str, conn) -> dict:
    """Fetch function names with their signatures."""
    query = """
    SELECT function_name, signature
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version))
        rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}


def json_to_natural_language(func_data: dict, adaptor_name: str = None, version: str = None) -> str:
    """
    Convert function JSON to natural language format for LLM consumption.
    """
    name = func_data.get("name", "")
    scope = func_data.get("scope", "global")
    function_name = name if scope == "global" else f"{scope}.{name}"

    nl = f"Function: {function_name}\n"

    if adaptor_name:
        nl += f"Adaptor: {adaptor_name}\n"
    if version:
        nl += f"Version: {version}\n"

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


def fetch_single_function(adaptor_name: str, version: str, function_name: str, conn, format: str = "json") -> dict | str:
    """
    Fetch a specific function's documentation.

    Args:
        format: "json" or "natural_language"
    """
    query = """
    SELECT function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s AND function_name = %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version, function_name))
        row = cur.fetchone()
        if row:
            func_data = row[0]  # JSONB data
            if format == "natural_language":
                return json_to_natural_language(func_data, adaptor_name, version)
            return func_data
        return None


def fetch_all_functions(adaptor_name: str, version: str, conn, format: str = "json") -> list:
    """
    Fetch all function documentation for an adaptor version.

    Args:
        format: "json" or "natural_language"
    """
    query = """
    SELECT function_name, function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version))
        rows = cur.fetchall()

        if format == "natural_language":
            return [
                {
                    "function_name": row[0],
                    "text": json_to_natural_language(row[1], adaptor_name, version)
                }
                for row in rows
            ]

        return [{"function_name": row[0], "data": row[1]} for row in rows]


def main(data: dict) -> dict:
    """
    Main entry point for searching adaptor function docs.

    Expected payload:
    {
        "adaptor": "@openfn/language-dhis2",
        "version": "4.2.10",
        "query_type": "list" | "signatures" | "function" | "all",
        "function_name": "create",  # Required if query_type is "function"
        "format": "json" | "natural_language",  # Optional, defaults to "json"
        "DATABASE_URL": "postgresql://..."  # Optional, will use env if not provided
    }
    """
    logger.info("Starting search_adaptor_docs...")

    # Validate required fields
    if "adaptor" not in data:
        raise ApolloError(400, "Missing required field: 'adaptor'", type="BAD_REQUEST")
    if "version" not in data:
        raise ApolloError(400, "Missing required field: 'version'", type="BAD_REQUEST")
    if "query_type" not in data:
        raise ApolloError(400, "Missing required field: 'query_type'", type="BAD_REQUEST")

    adaptor_name = data["adaptor"]
    version = data["version"]
    query_type = data["query_type"]
    function_name = data.get("function_name")
    format = data.get("format", "json")

    # Validate query_type
    valid_types = ["list", "signatures", "function", "all"]
    if query_type not in valid_types:
        raise ApolloError(400, f"Invalid query_type. Must be one of: {', '.join(valid_types)}", type="BAD_REQUEST")

    if query_type == "function" and not function_name:
        raise ApolloError(400, "Missing required field: 'function_name' for query_type='function'", type="BAD_REQUEST")

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
    logger.info(f"Querying {adaptor_name}@{version} (type: {query_type}, format: {format})")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise ApolloError(500, f"Database connection failed: {str(e)}", type="DATABASE_ERROR")

    try:
        if query_type == "list":
            # Return list of function names
            functions = fetch_function_list(adaptor_name, version, conn)
            logger.info(f"Found {len(functions)} functions")
            return {
                "adaptor": adaptor_name,
                "version": version,
                "query_type": "list",
                "functions": functions
            }

        elif query_type == "signatures":
            # Return function names with signatures
            signatures = fetch_signatures(adaptor_name, version, conn)
            logger.info(f"Found {len(signatures)} function signatures")
            return {
                "adaptor": adaptor_name,
                "version": version,
                "query_type": "signatures",
                "signatures": signatures
            }

        elif query_type == "function":
            # Fetch a specific function
            logger.info(f"Fetching function: {function_name}")
            func_data = fetch_single_function(adaptor_name, version, function_name, conn, format)
            if not func_data:
                raise ApolloError(404, f"Function '{function_name}' not found", type="NOT_FOUND")

            return {
                "adaptor": adaptor_name,
                "version": version,
                "query_type": "function",
                "function_name": function_name,
                "format": format,
                "data": func_data
            }

        elif query_type == "all":
            # Fetch all functions
            functions = fetch_all_functions(adaptor_name, version, conn, format)
            logger.info(f"Found {len(functions)} functions")
            return {
                "adaptor": adaptor_name,
                "version": version,
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

