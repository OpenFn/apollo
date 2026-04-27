def test_sanitize_job_names_removes_diacritics(workflow_chat_client):
    yaml_data = {
        "jobs": {
            "job1": {"name": "Café München"},
            "job2": {"name": "Naïve résumé"},
        }
    }

    workflow_chat_client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Cafe Munchen"
    assert yaml_data["jobs"]["job2"]["name"] == "Naive resume"


def test_sanitize_job_names_removes_special_characters(workflow_chat_client):
    yaml_data = {
        "jobs": {
            "job1": {"name": "Job@#$%Name!"},
            "job2": {"name": "Process&Data*With+Symbols"},
        }
    }

    workflow_chat_client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "JobName"
    assert yaml_data["jobs"]["job2"]["name"] == "ProcessDataWithSymbols"


def test_sanitize_job_names_preserves_allowed_characters(workflow_chat_client):
    yaml_data = {"jobs": {"job1": {"name": "Valid Job-Name_123"}}}

    workflow_chat_client.sanitize_job_names(yaml_data)

    assert yaml_data["jobs"]["job1"]["name"] == "Valid Job-Name_123"


def test_sanitize_job_names_handles_empty_data(workflow_chat_client):
    assert workflow_chat_client.sanitize_job_names(None) is None
    assert workflow_chat_client.sanitize_job_names({}) is None
    assert workflow_chat_client.sanitize_job_names({"jobs": {}}) is None
