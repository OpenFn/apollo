from workflow_chat.workflow_chat import AnthropicClient


def _make_client():
    # Bypass __init__ to skip anthropic.Anthropic() construction, which the
    # unit-tier guard blocks. The helpers under test never touch self.client.
    return object.__new__(AnthropicClient)


def test_extract_job_codes_preserves_real_code():
    client = _make_client()
    yaml_data = {
        "jobs": {
            "job1": {"body": "console.log('hello world')"},
            "job2": {"body": "const data = fetchData();\nprocessData(data);"},
        }
    }

    preserved_values, _ = client.extract_and_preserve_components(yaml_data)

    assert preserved_values == {
        "__CODE_BLOCK_job1__": "console.log('hello world')",
        "__CODE_BLOCK_job2__": "const data = fetchData();\nprocessData(data);",
    }


def test_extract_job_codes_ignores_default_placeholder():
    client = _make_client()
    yaml_data = {
        "jobs": {
            "job1": {"body": "// Add operations here"},
            "job2": {"body": "real code here"},
            "job3": {"body": "   // Add operations here   "},
        }
    }

    preserved_values, _ = client.extract_and_preserve_components(yaml_data)

    assert preserved_values == {"__CODE_BLOCK_job2__": "real code here"}
