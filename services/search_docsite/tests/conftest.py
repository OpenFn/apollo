"""Test config for search_docsite.

`search_docsite.search_docsite` constructs `OpenAIEmbeddings()` as a module-level
default argument, which (under openai 2.x / langchain-openai 1.x) validates
credentials at construction time. That happens when the test module is imported,
before any test runs — so a key must exist in the environment or import fails.

These are dummy placeholders only: unit tests inject mocks for every network
seam and the repo-root conftest additionally blocks real client construction, so
no real key is ever used. `setdefault` means a real key (from services/.env) wins.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("PINECONE_API_KEY", "pc-test-dummy")
