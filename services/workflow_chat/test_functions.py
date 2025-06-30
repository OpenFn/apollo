import pytest
from workflow_chat.workflow_chat import AnthropicClient, ChatConfig


@pytest.fixture
def client():
    """Create a client instance for testing."""
    return AnthropicClient(ChatConfig(api_key="fake-key"))


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