import json
import os
import sys
import psycopg2

def log(msg: str):
    print(f"[fetch] {msg}", file=sys.stderr)


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


def fetch_single_function(adaptor_name: str, version: str, function_name: str, conn) -> dict:
    """Fetch a specific function's documentation."""
    query = """
    SELECT function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s AND function_name = %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version, function_name))
        row = cur.fetchone()
        if row:
            return row[0]  # Return the JSONB data
        return None


def fetch_all_functions(adaptor_name: str, version: str, conn) -> list:
    """Fetch all function documentation for an adaptor version."""
    query = """
    SELECT function_name, function_data
    FROM adaptor_function_docs
    WHERE adaptor_name = %s AND version = %s
    ORDER BY function_name
    """

    with conn.cursor() as cur:
        cur.execute(query, (adaptor_name, version))
        rows = cur.fetchall()
        return [{"function_name": row[0], "data": row[1]} for row in rows]


def main():
    """Main entry point."""
    # Simple arg parsing
    args = {}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            if key in ("list-only", "signatures-only"):
                args[key] = True
                i += 1
            else:
                value = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
                args[key] = value
                i += 2
        else:
            i += 1

    adaptor_name = args.get("adaptor")
    version = args.get("version")
    function_name = args.get("function")
    list_only = args.get("list-only", False)
    signatures_only = args.get("signatures-only", False)

    if not adaptor_name or not version:
        print("Usage: python fetch_adaptor_functions.py --adaptor <name> --version <version> [--function <name>] [--list-only] [--signatures-only]")
        sys.exit(1)

    # Connect to PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log("Error: DATABASE_URL not set")
        sys.exit(1)

    log(f"Connecting to PostgreSQL")
    conn = psycopg2.connect(db_url)

    try:
        if list_only:
            # Just return the list of function names
            functions = fetch_function_list(adaptor_name, version, conn)
            log(f"Found {len(functions)} functions")
            print(json.dumps(functions, indent=2))

        elif signatures_only:
            # Return function names with signatures
            signatures = fetch_signatures(adaptor_name, version, conn)
            log(f"Found {len(signatures)} function signatures")
            print(json.dumps(signatures, indent=2))

        elif function_name:
            # Fetch a specific function
            log(f"Fetching function: {function_name}")
            data = fetch_single_function(adaptor_name, version, function_name, conn)
            if data:
                print(json.dumps(data, indent=2))
            else:
                log(f"Function '{function_name}' not found")
                sys.exit(1)

        else:
            # Fetch all functions
            log(f"Fetching all functions for {adaptor_name}@{version}")
            functions = fetch_all_functions(adaptor_name, version, conn)
            log(f"Found {len(functions)} functions")
            print(json.dumps(functions, indent=2))

    finally:
        conn.close()

