from workflow_chat.workflow_chat import AnthropicClient


def _make_client():
    # Bypass __init__ to skip anthropic.Anthropic() construction, which the
    # unit-tier guard blocks. The helpers under test never touch self.client.
    return object.__new__(AnthropicClient)


def test_sanitize_job_names_removes_diacritics():
    client = _make_client()
    yaml_data = {
        "jobs": {
            "job1": {"name": "Café München"},
            "job2": {"name": "Naïve résumé"},
        }
    }

    client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"
    assert yaml_data["jobs"]["job2"]["name"] == "Naive resume"


def test_sanitize_job_names_removes_special_characters():
    client = _make_client()
    yaml_data = {
        "jobs": {
            "job1": {"name": "Job@#$%Name!"},
            "job2": {"name": "Process&Data*With+Symbols"},
        }
    }

    client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "JobName"
    assert yaml_data["jobs"]["job2"]["name"] == "ProcessDataWithSymbols"


def test_sanitize_job_names_preserves_allowed_characters():
    client = _make_client()
    yaml_data = {"jobs": {"job1": {"name": "Valid Job-Name_123"}}}

    client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Valid Job-Name_123"


def test_sanitize_job_names_handles_empty_data():
    client = _make_client()
    assert client.sanitize_job_names(None) is None
    assert client.sanitize_job_names({}) is None
    assert client.sanitize_job_names({"jobs": {}}) is None
