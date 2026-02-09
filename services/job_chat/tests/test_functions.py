import pytest
from util import get_db_connection
from job_chat.prompt import generate_system_message


def test_generate_system_message_loads_adaptor_docs_when_missing():
    """
    Test that when adaptor docs are NOT in the database, generate_system_message()
    loads them via the pipeline and includes function signatures in the system message.

    This verifies the complete adaptor docs loading pipeline:
    1. Database is empty for the adaptor
    2. generate_system_message() is called with download_adaptor_docs=True
    3. Pipeline auto-loads docs from adaptor_apis service
    4. Function signatures appear in system message (not the fallback)
    5. Database now contains the adaptor docs
    """
    print("==================TEST==================")
    print("Description: Testing adaptor docs loading pipeline when docs missing from database")

    # Test configuration
    adaptor_name = "@openfn/language-http"
    version = "6.0.0"
    adaptor_specifier = f"{adaptor_name}@{version}"

    # Step 1: Clear adaptor from database
    print(f"\n1. Clearing {adaptor_specifier} from database...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM adaptor_function_docs WHERE adaptor_name = %s AND version = %s",
                (adaptor_name, version)
            )
            conn.commit()

            # Verify it's gone
            cur.execute(
                "SELECT COUNT(*) FROM adaptor_function_docs WHERE adaptor_name = %s AND version = %s",
                (adaptor_name, version)
            )
            count_before = cur.fetchone()[0]
            print(f"   Database cleared: {count_before} docs found (should be 0)")
            assert count_before == 0, "Setup failed: docs still in database after DELETE"
    finally:
        conn.close()

    # Step 2: Call generate_system_message() with download_adaptor_docs=True
    print(f"\n2. Calling generate_system_message() with adaptor {adaptor_specifier}...")
    context = {
        "adaptor": adaptor_specifier,
        "expression": "// test code"
    }

    system_message = generate_system_message(
        context_dict=context,
        search_results=None,
        download_adaptor_docs=True,  # This should trigger auto-loading
        stream_manager=None
    )

    print("   System message generated successfully")

    # Step 3: Assert adaptor docs are in system message (NOT the fallback)
    print("\n3. Verifying adaptor docs in system message...")

    # Combine all parts of system message into text
    system_text = ""
    for part in system_message:
        if isinstance(part, dict) and part.get("type") == "text":
            system_text += part["text"]
        elif isinstance(part, str):
            system_text += part

    # Key assertion: Should contain the SUCCESS marker, NOT the fallback
    assert "These are the available functions in the adaptor:" in system_text, \
        "System message should contain function list (proves signatures were loaded)"
    print("   ✓ Found success marker: 'These are the available functions in the adaptor:'")

    # Should NOT contain the fallback message
    assert "The user is using an OpenFn Adaptor to write the job." not in system_text, \
        "Should NOT contain fallback message (proves signatures loaded successfully)"
    print("   ✓ Fallback message NOT present (good - means signatures loaded)")

    # Should contain actual function signatures
    has_get = "get(" in system_text or "get (" in system_text
    assert has_get, "System message should include 'get' function signature"
    print("   ✓ Found 'get' function signature")

    has_post = "post(" in system_text or "post (" in system_text
    assert has_post, "System message should include 'post' function signature"
    print("   ✓ Found 'post' function signature")

    # Step 4: Verify database now has docs
    print("\n4. Verifying database now contains adaptor docs...")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), array_agg(function_name) FROM adaptor_function_docs WHERE adaptor_name = %s AND version = %s",
                (adaptor_name, version)
            )
            count_after, function_names = cur.fetchone()

            print(f"   Database now has {count_after} functions")
            assert count_after > 0, "Adaptor docs should now be in database"

            # Verify specific functions exist
            assert function_names is not None, "Function names should not be None"
            assert "get" in function_names, "Should have 'get' function in database"
            print("   ✓ 'get' function in database")

            assert "post" in function_names, "Should have 'post' function in database"
            print("   ✓ 'post' function in database")

            print(f"\n✅ TEST PASSED: Complete pipeline verified")
            print(f"   - Docs were auto-loaded from adaptor_apis")
            print(f"   - Function signatures added to system message")
            print(f"   - {count_after} functions stored in database")
    finally:
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
