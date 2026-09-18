"""Test config for search_documentation unit tests.

Importing `search_documentation.search_documentation` pulls in
`search_docsite.pinecone_legacy_search`, whose module-level `OpenAIEmbeddings()`
default arg validates credentials at construction (openai 2.x / langchain-openai 1.x).
A key must therefore exist at import time.

Dummy placeholders only.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("PINECONE_API_KEY", "pc-test-dummy")
