#!/usr/bin/env python3
"""
Concurrent database write test for load_adaptor_docs.

Tests what happens when 10 requests try to write to the database simultaneously.
This simulates high load scenarios where multiple adaptor docs are being loaded at once.
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import psycopg2
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Sample documentation data for testing
SAMPLE_FUNCTION_DOC = {
    "name": "testFunction",
    "scope": "global",
    "signature": "testFunction(arg: string): Operation",
    "description": "A test function for concurrent write testing",
    "params": [
        {
            "name": "arg",
            "type": ["string"],
            "description": "Test argument"
        }
    ],
    "examples": ["testFunction('hello')"],
    "returns": [{"type": ["Operation"]}]
}


def create_test_docs(adaptor_name: str, version: str, num_functions: int = 5) -> List[Dict[str, Any]]:
    """Generate test documentation data."""
    docs = []
    for i in range(num_functions):
        doc = SAMPLE_FUNCTION_DOC.copy()
        doc["name"] = f"testFunction{i}"
        doc["signature"] = f"testFunction{i}(arg: string): Operation"
        docs.append(doc)
    return docs


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


def upload_to_postgres(
    adaptor_name: str,
    version: str,
    filtered_docs: List[Dict[str, Any]],
    db_url: str,
    worker_id: int
) -> Dict[str, Any]:
    """
    Upload filtered function docs to PostgreSQL.
    This mimics the actual upload_to_postgres function from load_adaptor_docs.py
    """
    start_time = time.time()

    try:
        # Create a new connection for this worker
        conn = psycopg2.connect(db_url)

        # Delete existing rows for this adaptor version
        delete_sql = """
        DELETE FROM adaptor_function_docs
        WHERE adaptor_name = %s AND version = %s
        """

        with conn.cursor() as cur:
            cur.execute(delete_sql, (adaptor_name, version))
            deleted_count = cur.rowcount
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
        from psycopg2.extras import execute_values
        insert_sql = """
        INSERT INTO adaptor_function_docs
            (adaptor_name, version, function_name, signature, function_data)
        VALUES %s
        """

        with conn.cursor() as cur:
            execute_values(cur, insert_sql, rows)
            conn.commit()

        elapsed = time.time() - start_time

        return {
            "success": True,
            "worker_id": worker_id,
            "adaptor": adaptor_name,
            "version": version,
            "functions_uploaded": len(rows),
            "deleted_count": deleted_count,
            "elapsed_seconds": round(elapsed, 3)
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "worker_id": worker_id,
            "adaptor": adaptor_name,
            "version": version,
            "error": str(e),
            "error_type": type(e).__name__,
            "elapsed_seconds": round(elapsed, 3)
        }
    finally:
        conn.close()


def run_concurrent_writes(db_url: str, num_workers: int = 10) -> Dict[str, Any]:
    """
    Run concurrent database writes using ThreadPoolExecutor.

    Args:
        db_url: PostgreSQL connection URL
        num_workers: Number of concurrent workers (default 10)

    Returns:
        Dictionary with test results and statistics
    """
    print(f"\n{'='*60}")
    print(f"Starting concurrent database write test")
    print(f"Workers: {num_workers}")
    print(f"{'='*60}\n")

    # Create table first
    conn = psycopg2.connect(db_url)
    create_table_if_not_exists(conn)
    conn.close()

    # Prepare test data for each worker
    # Each worker writes to a different adaptor to test concurrent INSERT operations
    # Some workers write to the same adaptor to test DELETE race conditions
    tasks = []
    for i in range(num_workers):
        if i < 10:
            # First 10 workers: different adaptors (no conflicts expected)
            adaptor_name = f"@openfn/language-test{i}"
        else:
            # Last 10 workers: same 5 adaptors (conflicts expected)
            adaptor_name = f"@openfn/language-shared{i % 5}"

        version = "1.0.0"
        docs = create_test_docs(adaptor_name, version, num_functions=5)

        tasks.append({
            "worker_id": i,
            "adaptor_name": adaptor_name,
            "version": version,
            "docs": docs
        })

    # Run all tasks concurrently
    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(
                upload_to_postgres,
                task["adaptor_name"],
                task["version"],
                task["docs"],
                db_url,
                task["worker_id"]
            ): task
            for task in tasks
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            status = "✓" if result["success"] else "✗"
            worker_id = result["worker_id"]
            elapsed = result["elapsed_seconds"]

            if result["success"]:
                print(f"{status} Worker {worker_id:2d}: {result['adaptor']:40s} - {elapsed}s (deleted {result['deleted_count']})")
            else:
                print(f"{status} Worker {worker_id:2d}: {result['adaptor']:40s} - {elapsed}s - ERROR: {result['error']}")

    total_elapsed = time.time() - start_time

    # Calculate statistics
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    print(f"\n{'='*60}")
    print("Test Results:")
    print(f"{'='*60}")
    print(f"Total elapsed time: {total_elapsed:.3f}s")
    print(f"Successful writes:  {len(successes)}/{num_workers}")
    print(f"Failed writes:      {len(failures)}/{num_workers}")

    if successes:
        avg_time = sum(r["elapsed_seconds"] for r in successes) / len(successes)
        min_time = min(r["elapsed_seconds"] for r in successes)
        max_time = max(r["elapsed_seconds"] for r in successes)
        print(f"\nTiming (successful writes):")
        print(f"  Average: {avg_time:.3f}s")
        print(f"  Min:     {min_time:.3f}s")
        print(f"  Max:     {max_time:.3f}s")

    if failures:
        print(f"\nErrors encountered:")
        error_types = {}
        for failure in failures:
            error_type = failure.get("error_type", "Unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1

        for error_type, count in error_types.items():
            print(f"  {error_type}: {count}")

        print(f"\nDetailed errors:")
        for failure in failures:
            print(f"  Worker {failure['worker_id']}: {failure['error']}")

    print(f"{'='*60}\n")

    # Verify data integrity - check for incomplete writes
    print("Verifying data integrity...")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # Check that all adaptors have exactly 5 functions
            cur.execute("""
                SELECT adaptor_name, version, COUNT(*) as function_count
                FROM adaptor_function_docs
                WHERE adaptor_name LIKE '%test%' OR adaptor_name LIKE '%shared%'
                GROUP BY adaptor_name, version
                HAVING COUNT(*) != 5
            """)
            incomplete_adaptors = cur.fetchall()

            if incomplete_adaptors:
                print("⚠️  WARNING: Found adaptors with incomplete data:")
                for adaptor_name, version, count in incomplete_adaptors:
                    print(f"  {adaptor_name}@{version}: {count} functions (expected 5)")
            else:
                print("✓ All adaptors have complete data (5 functions each)")

            # Count total adaptors
            cur.execute("""
                SELECT COUNT(DISTINCT adaptor_name)
                FROM adaptor_function_docs
                WHERE adaptor_name LIKE '%test%' OR adaptor_name LIKE '%shared%'
            """)
            total_adaptors = cur.fetchone()[0]
            print(f"✓ Total unique adaptors in database: {total_adaptors}")

    finally:
        conn.close()

    print()

    return {
        "total_elapsed": total_elapsed,
        "successes": len(successes),
        "failures": len(failures),
        "results": results
    }


def main():
    """Main entry point for the test."""
    db_url = os.environ.get("POSTGRES_URL")

    if not db_url:
        print("ERROR: POSTGRES_URL environment variable not set")
        print("Please set POSTGRES_URL in your .env file or environment")
        return 1

    try:
        # Test with 20 concurrent workers
        results = run_concurrent_writes(db_url, num_workers=20)

        # Return exit code based on results
        if results["failures"] > 0:
            print("⚠️  Some writes failed - check logs above")
            return 1
        else:
            print("✓ All writes succeeded!")
            return 0

    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())