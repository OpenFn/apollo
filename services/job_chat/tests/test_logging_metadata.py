import sys
import unittest
from pathlib import Path


services_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(services_dir))

from job_chat.logging_metadata import build_request_log_metadata


class TestLoggingMetadata(unittest.TestCase):
    def test_build_request_log_metadata_uses_types_not_values(self):
        payload = {
            "_request_id": "req-123",
            "content": "secret user question",
            "history": [{"role": "user", "content": "hello"}],
            "context": {
                "expression": "fn(state => state)",
                "input": {"data": {"secret": "value"}},
                "log": "sensitive runtime output",
            },
            "meta": {"rag": {"search_results": []}},
            "api_key": "sk-ant-123",
            "stream": False,
            "suggest_code": True,
        }

        metadata = build_request_log_metadata(payload)

        self.assertEqual(metadata["request_id"], "req-123")
        self.assertEqual(
            metadata["payload_shape"],
            {
                "content": "string",
                "history": "array",
                "context": "object",
                "meta": "object",
                "api_key": "redacted",
                "stream": "boolean",
                "suggest_code": "boolean",
            },
        )
        self.assertEqual(metadata["history_length"], 1)
        self.assertEqual(metadata["context_keys"], ["expression", "input", "log"])
        self.assertEqual(
            metadata["context_shape"],
            {
                "expression": "string",
                "input": "object",
                "log": "string",
            },
        )

        metadata_text = str(metadata)
        self.assertNotIn("secret user question", metadata_text)
        self.assertNotIn("sensitive runtime output", metadata_text)
        self.assertNotIn("sk-ant-123", metadata_text)

    def test_build_request_log_metadata_handles_missing_optional_fields(self):
        metadata = build_request_log_metadata({"content": "hi"})

        self.assertIsNone(metadata["request_id"])
        self.assertEqual(
            metadata["payload_shape"],
            {
                "content": "string",
            },
        )
        self.assertEqual(metadata["history_length"], 0)
        self.assertEqual(metadata["context_keys"], [])
        self.assertEqual(metadata["context_shape"], {})


if __name__ == "__main__":
    unittest.main()
