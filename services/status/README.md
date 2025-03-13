# Status

This a service that tests whether API keys are working. It check for Anthropic, OpenAI and Pinecone keys from the environment. It does not cost tokens to use.

## Usage

This service can be run from the services folder via the entry.py module. The input is an empty JSON:

```bash
python entry.py status --input tmp/input.json
```
