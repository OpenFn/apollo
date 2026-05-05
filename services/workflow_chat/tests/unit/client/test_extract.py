from workflow_chat.workflow_chat import AnthropicClient


def test_extract_job_codes_preserves_real_code():
    yaml_data = {
        "jobs": {
            "job1": {"body": "console.log('hello world')"},
            "job2": {"body": "const data = fetchData();\nprocessData(data);"},
        }
    }

    preserved_values, _ = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert preserved_values == {
        "__CODE_BLOCK_job1__": "console.log('hello world')",
        "__CODE_BLOCK_job2__": "const data = fetchData();\nprocessData(data);",
    }


def test_extract_job_codes_ignores_default_placeholder():
    yaml_data = {
        "jobs": {
            "job1": {"body": "// Add operations here"},
            "job2": {"body": "real code here"},
            "job3": {"body": "   // Add operations here   "},
        }
    }

    preserved_values, _ = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert preserved_values == {"__CODE_BLOCK_job2__": "real code here"}
