# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

**Never chain Bash commands with `&&`, `;`, or `cd ... &&`. Use separate Bash
calls instead.**

## Commands

### Development

- `bun dev` - Start hot-reloading development server (watches TypeScript files)
- `bun start` - Start production server
- `bun py <service> --input <input.json>` - Run Python service directly via
  entry.py (bypasses HTTP, same execution path as server)

### Python Dependencies

- `poetry install` - Install Python dependencies (creates in-project `.venv`)
- `poetry add <module>` - Add a new Python dependency
- `ruff check <path>` - Lint Python (ruff is a dev dependency); only lint files
  you changed

### Tests

- `bun test` - TypeScript tests (`platform/test/`)
- `poetry run pytest services/<service>/tests/` - Python service tests (run from
  the repo root). Chat-agent suites split into `test_pass_fail.py` (strict
  assertions) and `test_qualitative.py` (prints output for review); pass `-s` to
  see it. These hit live LLM APIs and cost tokens.

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
- **Instance auth** (`platform/src/middleware/auth.ts`): `/services/*` is gated by
  a bearer token only when `POSTGRES_URL` is set AND the `lightning_clients` table
  exists (opt-in; otherwise open). A matched client's stored Anthropic key is
  injected into the payload as `api_key`. Health endpoints and loopback/internal
  `apollo()` calls are exempt. Provisioning lives in `services/_instance_auth/`.

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
- `get_db_connection()` - psycopg2 connection from `POSTGRES_URL` (used by the
  Postgres-backed adaptor-doc services)
- `sum_usage(*usages)` - Aggregate Anthropic token/cache usage across calls
- `add_page_prefix(content, page)` - Tag a message with `[pg:type/name/adaptor]`
  for client-side navigation

### Models (`services/models.py`)

Central Claude model config. Use the `CLAUDE_OPUS` / `CLAUDE_SONNET` /
`CLAUDE_HAIKU` constants or `resolve_model(alias)` rather than hardcoding model
IDs anywhere. All chat/agent services use Anthropic; OpenAI is used **only** for
embeddings (`OpenAIEmbeddings`).

### Observability (`services/langfuse_util.py`)

Langfuse tracing is initialised in `entry.py` and applied per-service with
`@observe`. It is opt-in per request: `should_track(data_dict)` checks the
`metrics_opt_in` flag on the payload. Keys: `LANGFUSE_SECRET_KEY`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`.

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
- `doc_agent_chat/` - Agentic chat over a project's uploaded documents (RAG via
  the `doc-agent` Pinecone index, one namespace per project).
- `doc_agent_upload/` - Fetches and indexes project documents into the
  `doc-agent` index under a `project-{id}` namespace.
- `search_docsite/` - Semantic search over OpenFn docs (reads the `docsite`
  Pinecone index; used by job_chat and global_chat for dynamic context).
- `embed_docsite/` - Downloads and indexes the OpenFn docs into the `docsite`
  index.
- `load_adaptor_docs/` / `search_adaptor_docs/` - Parse adaptor function docs
  into Postgres and query them back by version (Postgres-backed, not vector).
- `latest_adaptors/` - Fetches the latest adaptor versions from the OpenFn repo.
- `adaptor_apis/` - **TypeScript** service: produces a JSON schema of an
  adaptor's API.
- `vocab_mapper/` + `embeddings/` - Maps medical vocabularies (LOINC/SNOMED)
  against the `apollo-mappings` Pinecone index (collections `loinc-mappings-v2`,
  `snomed-mappings`). `embed_loinc_dataset` / `embed_snomed_dataset` populate it.
- `status/` - Health check: validates Anthropic, OpenAI and Pinecone keys.
- `echo/` - Test service that returns its input; useful for verifying the server
  pipeline.

Note: there are **three distinct Pinecone indexes** — `docsite` (OpenFn docs),
`doc-agent` (user uploads, per-project namespaces), and `apollo-mappings`
(medical vocab only). They are not interchangeable.

### Testing (`services/testing/`)

Shared acceptance-test harness (YAML specs, LLM-as-judge, an Apollo client
stub), used by the chat-agent test suites. Not a mounted service (it has no
`testing.py` index file).

### Environment

- **Python 3.11 exactly** (recommend asdf with python plugin)
- **Poetry** with in-project `.venv` (configured in `poetry.toml`)
- **`.env` file** at root for API keys (OpenAI, Anthropic, Pinecone, Postgres,
  Sentry DSN, Langfuse) — see `.env.example`
- **Sentry** + **Langfuse** integration in entry.py (Sentry trace sampling is
  environment-based; Langfuse is opt-in per request via `metrics_opt_in`)
- **Vector store**: Pinecone, with three separate indexes (`docsite`,
  `doc-agent`, `apollo-mappings`) — see Key Python Services above. Embeddings are
  generated with OpenAI.
