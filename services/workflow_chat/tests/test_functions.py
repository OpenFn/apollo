import pytest
from workflow_chat.workflow_chat import AnthropicClient, ChatConfig
from workflow_chat.gen_project_prompt import build_prompt


@pytest.fixture
def client():
    """Create a client instance for testing."""
    return AnthropicClient(ChatConfig(api_key="fake-key"))

def test_extract_job_codes_preserves_real_code(client):
    """Test that actual code is extracted and preserved."""
    
    yaml_data = {
        "jobs": {
            "job1": {"body": "console.log('hello world')"},
            "job2": {"body": "const data = fetchData();\nprocessData(data);"}
        }
    }
    
    preserved_values, processed_yaml = client.extract_and_preserve_components(yaml_data)
    
    assert len(preserved_values) == 2
    assert preserved_values["__CODE_BLOCK_job1__"] == "console.log('hello world')"
    assert preserved_values["__CODE_BLOCK_job2__"] == "const data = fetchData();\nprocessData(data);"


def test_extract_job_codes_ignores_default_placeholder(client):
    """Test that default placeholder is not preserved as code."""
    
    yaml_data = {
        "jobs": {
            "job1": {"body": "// Add operations here"},
            "job2": {"body": "real code here"},
            "job3": {"body": "   // Add operations here   "}  # with whitespace
        }
    }
    
    preserved_values, processed_yaml = client.extract_and_preserve_components(yaml_data)
    
    assert len(preserved_values) == 1
    assert "__CODE_BLOCK_job1__" not in preserved_values
    assert "__CODE_BLOCK_job3__" not in preserved_values
    assert preserved_values["__CODE_BLOCK_job2__"] == "real code here"


def test_sanitize_job_names_removes_diacritics(client):
    """Test that diacritics are properly normalized and removed."""
    
    yaml_data = {
        "jobs": {
            "job1": {"name": "Café München"},
            "job2": {"name": "Naïve résumé"}
        }
    }
    
    client.sanitize_job_names(yaml_data)
    
    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"
    assert yaml_data["jobs"]["job2"]["name"] == "Naive resume"


def test_sanitize_job_names_removes_special_characters(client):
    """Test that special characters are properly removed."""
    
    yaml_data = {
        "jobs": {
            "job1": {"name": "Job@#$%Name!"},
            "job2": {"name": "Process&Data*With+Symbols"}
        }
    }
    
    client.sanitize_job_names(yaml_data)
    
    assert yaml_data["jobs"]["job1"]["name"] == "JobName"
    assert yaml_data["jobs"]["job2"]["name"] == "ProcessDataWithSymbols"


def test_sanitize_job_names_preserves_allowed_characters(client):
    """Test that alphanumeric, spaces, hyphens, and underscores are preserved."""
    
    yaml_data = {
        "jobs": {
            "job1": {"name": "Valid Job-Name_123"}
        }
    }
    
    client.sanitize_job_names(yaml_data)
    
    assert yaml_data["jobs"]["job1"]["name"] == "Valid Job-Name_123"


def test_sanitize_job_names_handles_empty_data(client):
    """Test that function handles edge cases gracefully."""

    # Should not raise exceptions and return without error
    result1 = client.sanitize_job_names(None)
    result2 = client.sanitize_job_names({})
    result3 = client.sanitize_job_names({"jobs": {}})

    assert result1 is None
    assert result2 is None
    assert result3 is None


def test_build_prompt_normal_mode():
    """Test that normal mode uses correct configuration."""
    system_msg, prompt = build_prompt(
        content='Create a workflow',
        existing_yaml='name: test-workflow',
        history=[{'role': 'user', 'content': 'Hello'}]
    )

    # Should use normal mode configuration
    assert 'talk to a client with the goal of converting' in system_msg  # normal_mode_intro
    assert 'You can either' in system_msg  # normal_mode_answering_instructions
    assert 'user is currently editing this YAML' in system_msg
    assert 'name: test-workflow' in system_msg

    # Prompt structure
    assert len(prompt) == 2
    assert prompt[-1]['content'] == 'Create a workflow'


def test_build_prompt_error_mode():
    """Test that error mode uses correct configuration and appends error message."""
    system_msg, prompt = build_prompt(
        content='Fix the workflow',
        existing_yaml='name: broken-workflow',
        errors='Invalid trigger type',
        history=[]
    )

    # Should use error mode configuration
    assert 'Your previous suggestion produced an invalid' in system_msg  # error_mode_intro
    assert 'Answer with BOTH the' in system_msg  # error_mode_answering_instructions
    assert 'YAML causing the error' in system_msg
    assert 'name: broken-workflow' in system_msg

    # User content should have error appended
    assert prompt[-1]['content'] == 'Fix the workflow\nThis is the error message:\nInvalid trigger type'


def test_build_prompt_readonly_mode():
    """Test that readonly mode uses unstructured output format."""
    system_msg, prompt = build_prompt(
        content='What does this workflow do?',
        existing_yaml='name: readonly-workflow',
        read_only=True,
        history=[]
    )

    # Should use readonly mode configuration
    assert 'Read-only Mode' in system_msg  # unstructured_output_format
    assert 'triple-backticked YAML code blocks' in system_msg  # readonly_mode_answering_instructions
    assert 'user is viewing this read-only YAML' in system_msg
    assert 'name: readonly-workflow' in system_msg

    # User content should be unchanged
    assert prompt[-1]['content'] == 'What does this workflow do?'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])