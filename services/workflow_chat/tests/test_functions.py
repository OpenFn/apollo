import pytest
from workflow_chat.workflow_chat import AnthropicClient, ChatConfig


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
    
    result = client.extract_job_codes(yaml_data)
    
    assert len(result) == 2
    assert result["job1"]["code"] == "console.log('hello world')"
    assert result["job2"]["code"] == "const data = fetchData();\nprocessData(data);"
    assert result["job1"]["placeholder"] == "__CODE_BLOCK_job1__"
    assert result["job2"]["placeholder"] == "__CODE_BLOCK_job2__"


def test_extract_job_codes_ignores_default_placeholder(client):
    """Test that default placeholder is not preserved as code."""
    
    yaml_data = {
        "jobs": {
            "job1": {"body": "// Add operations here"},
            "job2": {"body": "real code here"},
            "job3": {"body": "   // Add operations here   "}  # with whitespace
        }
    }
    
    result = client.extract_job_codes(yaml_data)
    
    assert len(result) == 1
    assert "job1" not in result
    assert "job3" not in result
    assert result["job2"]["code"] == "real code here"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])