import pytest
import json
import os
from pathlib import Path
from entry import call, main
import argparse
from unittest.mock import patch
from util import apollo, set_fork_call


def setup_module():
    """Setup test directories"""
    Path("tmp/data").mkdir(parents=True, exist_ok=True)


def test_minimal_call():
    """Test calling with just the service name"""
    result = call("echo")
    assert result == {}


def test_call_with_input():
    """Test calling with service name and input"""
    input_path = "tmp/test_input.json"
    test_data = {"test": "data"}

    with open(input_path, "w") as f:
        json.dump(test_data, f)

    result = call("echo", input_path=input_path)
    assert result == test_data


def test_command_line_minimal():
    """Test the absolute minimum command line usage"""
    test_args = argparse.Namespace(service="echo", input=None, output=None, port=None)

    with patch("argparse.ArgumentParser.parse_args", return_value=test_args):
        result = main()
        assert result == {}


def test_auto_generated_output():
    """Test that output path is auto-generated when not provided"""
    test_args = argparse.Namespace(service="echo", input=None, output=None, port=None)

    with patch("argparse.ArgumentParser.parse_args", return_value=test_args):
        main()
        files = list(Path("tmp/data").glob("*.json"))
        assert len(files) > 0


def test_apollo_http_fallback_uses_port():
    """With no fork transport installed, apollo() falls back to an HTTP
    self-call at the configured port (the spawn/standalone path)."""
    test_args = argparse.Namespace(service="echo", input=None, output=None, port=5000)

    with patch("argparse.ArgumentParser.parse_args", return_value=test_args):
        main()  # sets the apollo port to 5000

        set_fork_call(None)  # ensure the HTTP path is taken
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"test": "data"}
            result = apollo("test", {"a": 1})
            # no internal auth header is sent any more
            mock_post.assert_called_with(
                "http://127.0.0.1:5000/services/test", json={"a": 1}
            )
            assert result == {"test": "data"}


def test_apollo_routes_through_fork_transport():
    """When entry.fork has installed a transport, apollo() rides it (the
    CALL/REPLY socket path) instead of making any HTTP call."""
    calls = []

    def fake_transport(service: str, payload: dict) -> dict:
        calls.append((service, payload))
        return {"docs": {"@openfn/language-http@3.1.11": "..."}, "errors": []}

    set_fork_call(fake_transport)
    try:
        with patch("requests.post") as mock_post:
            result = apollo("adaptor_apis", {"adaptors": ["http@3.1.11"]})
            mock_post.assert_not_called()  # no second HTTP hop
        assert calls == [("adaptor_apis", {"adaptors": ["http@3.1.11"]})]
        assert result["docs"]["@openfn/language-http@3.1.11"] == "..."
    finally:
        set_fork_call(None)


def test_invalid_service():
    """Test handling of invalid service name"""
    result = call("nonexistent_service")
    assert result["type"] == "INTERNAL_ERROR"
    assert result["code"] == 500
    assert "No module named" in result["message"]


def test_invalid_input_file():
    """Test handling of nonexistent input file"""
    try:
        result = call("echo", input_path="nonexistent.json")
        assert result["type"] == "INTERNAL_ERROR"
        assert result["code"] == 500
    except FileNotFoundError:
        pytest.fail("FileNotFoundError should be caught and returned as error dict")


def test_output_file_writing():
    """Test that output is written to specified file"""
    output_path = "tmp/test_output.json"
    test_data = {"test": "data"}

    result = call("echo", output_path=output_path)

    assert os.path.exists(output_path)
    with open(output_path, "r") as f:
        written_data = json.load(f)
    assert written_data == result


def teardown_module():
    """Clean up test files"""
    for f in Path("tmp").glob("test_*.json"):
        f.unlink(missing_ok=True)
