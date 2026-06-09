"""Test config for job_chat unit tests.

Importing `job_chat.retrieve_docs` pulls in `search_docsite.search_docsite`, whose
module-level `OpenAIEmbeddings()` default arg validates credentials at construction
(openai 2.x / langchain-openai 1.x). A key must therefore exist at import time.

Dummy placeholders only — unit tests mock every network seam, and the repo-root
conftest blocks real client construction. `setdefault` lets a real key win.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("PINECONE_API_KEY", "pc-test-dummy")
