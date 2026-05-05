from workflow_chat.workflow_chat import AnthropicClient


def test_sanitize_job_names_removes_diacritics():
    yaml_data = {
        "jobs": {
            "job1": {"name": "Café München"},
            "job2": {"name": "Naïve résumé"},
        }
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"
    assert yaml_data["jobs"]["job2"]["name"] == "Naive resume"


def test_sanitize_job_names_removes_special_characters():
    yaml_data = {
        "jobs": {
            "job1": {"name": "Job@#$%Name!"},
            "job2": {"name": "Process&Data*With+Symbols"},
        }
    }

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "JobName"
    assert yaml_data["jobs"]["job2"]["name"] == "ProcessDataWithSymbols"


def test_sanitize_job_names_preserves_allowed_characters():
    yaml_data = {"jobs": {"job1": {"name": "Valid Job-Name_123"}}}

    AnthropicClient.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Valid Job-Name_123"


def test_sanitize_job_names_handles_empty_data():
    assert AnthropicClient.sanitize_job_names(None) is None
    assert AnthropicClient.sanitize_job_names({}) is None
    assert AnthropicClient.sanitize_job_names({"jobs": {}}) is None
