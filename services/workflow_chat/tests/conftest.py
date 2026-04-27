import pytest

from workflow_chat.workflow_chat import AnthropicClient


@pytest.fixture
def workflow_chat_client():
    """An `AnthropicClient` for testing pure helper methods.

    `AnthropicClient.__init__` instantiates `anthropic.Anthropic(...)`, which
    the unit-tier guard blocks. The helpers we exercise never touch
    `self.client`, so we bypass `__init__` to skip SDK construction. Tests
    that need `self.client` belong in the service tier.
    """
    return object.__new__(AnthropicClient)
