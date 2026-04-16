# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Commands

### Development

- `bun dev` - Start hot-reloading development server (watches TypeScript files)
- `bun start` - Start production server
- `bun test` - Run TypeScript tests (uses `bun:test`, files in `platform/test/`)
- `bun py <service> --input <input.json>` - Run Python service directly via
  entry.py (bypasses HTTP, same execution path as server)

### Python Dependencies

- `poetry install` - Install main Python dependencies (creates `.venv` in
  project)
- `poetry install --with ft` - Also install finetuning dependencies (large
  models)
- `poetry add <module>` - Add a new Python dependency

## Architecture

Hybrid TypeScript/Python platform providing AI and data services for the OpenFn
platform. Bun+Elysia server routes HTTP/WebSocket/SSE requests to Python (or
TypeScript) service modules.

### Server Layer (TypeScript)

- **Entry**: `platform/src/index.ts` → `platform/src/server.ts`
- **Framework**: Elysia on Bun runtime
- **Bridge**: `platform/src/bridge.ts` - Spawns Python as child processes,
  manages temp files in `tmp/data/`, captures stdout for log/event routing
- **Service discovery**: `platform/src/util/describe-modules.ts` - Auto-mounts
  any `services/<name>/` directory not starting with `_`. Detects service type
  by checking for `<name>.py` (Python) or `<name>.ts` (TypeScript) index file.

### Services Architecture

Each service lives in `services/<name>/` with an index file
`services/<name>/<name>.py` (or `.ts`) exporting a `main()` function.

- **Python**: `main(data_dict: dict) -> dict` — see `.claude/rules/python-services.md`
  for details on entry.py, imports, and code quality
- **TypeScript**: `export default (port, payload, onLog?) => Promise<any>`

Every mounted service gets three endpoints automatically:

- `POST /services/<name>` - Synchronous JSON request/response
- `POST /services/<name>/stream` - SSE streaming (events: `log`, `complete`,
  `error`, plus custom event types)
- `WS /services/<name>` - WebSocket with `start`/`log`/`complete` events

### Key Shared Utilities (`services/util.py`)

- `create_logger(name)` - Logger whose output streams to WebSocket/SSE clients
  (use `print()` for private/debug logging only)
- `ApolloError(code, message, type, details)` - Dataclass exception; returned
  errors with a `code` field get mapped to HTTP status codes by the bridge
- `apollo(name, payload)` - Call another Apollo service via HTTP (for
  inter-service communication)
- `DictObj(dict)` - Dot-accessible dictionary wrapper
- `AdaptorSpecifier(str)` - Parses adaptor strings like
  `"@openfn/language-http@3.1.11"` or `"http@3.1.11"`

### Streaming (`services/streaming_util.py`)

`StreamManager` emits Anthropic-formatted SSE events (message_start,
content_block_start/delta/stop, message_delta, message_stop) through the
`EVENT:type:json` protocol that `bridge.ts` captures from stdout and forwards as
SSE to clients.

### Key Python Services

- `global_chat/` - Orchestrator service and single entry point for OpenFn AI
  chat. Routes requests via a RouterAgent (Haiku) to specialized subagents, or
  escalates to a PlannerAgent (Sonnet) that coordinates multi-step tasks using
  tool calls. Depends on `job_chat`, `workflow_chat`, and `search_docsite`.
- `job_chat/` - AI chat service for OpenFn job code assistance. Supports
  conversational help and a code suggestions mode with auto-patching. Uses RAG
  via `search_docsite` and injects adaptor API docs. Streams responses.
- `workflow_chat/` - AI chat service for generating and editing OpenFn workflow
  YAML. Preserves job code and IDs during edits, validates adaptors, and retries
  on parse failures. Streams responses.
- `search_docsite/` - Searches OpenFn docs using Pinecone vector store (used by
  job_chat and global_chat for dynamic context)
- `embed_docsite/` - Indexes OpenFn documentation for search
- `embeddings/` - Vector embeddings with Pinecone (production index:
  "apollo-mappings")
- `vocab_mapper/` - Maps medical vocabularies (LOINC/SNOMED) using embeddings
- `echo/` - Test service that returns its input; useful for verifying the server
  pipeline

### Environment

- **Python 3.11 exactly** (recommend asdf with python plugin)
- **Poetry** with in-project `.venv` (configured in `poetry.toml`)
- **`.env` file** at root for API keys (OpenAI, Pinecone, Sentry DSN,
  POSTGRES_URL)
- **Sentry** integration in entry.py with environment-based trace sampling
- **Vector store**: Pinecone index "apollo-mappings" with namespace-based
  collections
