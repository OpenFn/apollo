import pytest
import yaml
from workflow_chat.workflow_chat import AnthropicClient
from yaml_utils import WITHHELD_NOTICE


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


@pytest.mark.parametrize(
    "document",
    [
        "- body: const API_KEY = 'sk-live-do-not-log-me';\n",
        "just a string\n",
    ],
)
def test_a_document_that_is_not_a_mapping_is_withheld(document: str) -> None:
    """`"jobs" in yaml_data` is a membership test over a list's items rather
    than a key lookup, so a top-level sequence swapped nothing for a placeholder
    and the document went into the prompt with every job body intact."""
    yaml_data = yaml.safe_load(document)

    preserved_values, processed = AnthropicClient.extract_and_preserve_components(yaml_data)

    assert preserved_values == {}
    assert processed == WITHHELD_NOTICE
    assert "sk-live-do-not-log-me" not in processed
