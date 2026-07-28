"""Test config for embed_docsite unit tests.

Importing `embed_docsite.pinecone_legacy_indexer` pulls in
`LegacyPineconeDocsiteIndexer`, whose module-level `OpenAIEmbeddings()`
default arg validates credentials at construction (openai 2.x / langchain-openai 1.x).
A key must therefore exist at import time.

Dummy placeholders only: unit tests mock every real network call, so no real
key is ever used. `setdefault` means a real key (from services/.env) wins.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("PINECONE_API_KEY", "pc-test-dummy")
