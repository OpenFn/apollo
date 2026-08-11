---
"apollo": patch
---

search_docsite: create the default OpenAIEmbeddings client lazily so
importing the module (e.g. via global chat's tool imports) no longer
crashes without OPENAI_API_KEY
