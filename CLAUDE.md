# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
- `bun dev` - Start hot-reloading development server (watches TypeScript files)
- `bun start` - Start production server
- `bun test platform/test` - Run TypeScript tests
- `bun py <service> <input.json>` - Run Python service directly via entry.py

### Python Setup
- `poetry install` - Install main Python dependencies
- `poetry install --with ft` - Install with fine-tuning dependencies (includes large ML models)
- `poetry install --with dev` - Install with development dependencies

### Testing Python Services
- `pytest services/<service>/tests/` - Run tests for specific service
- `pytest` - Run all Python tests

### Code Quality
- `black services/` - Format Python code (line length: 120)
- `ruff check services/` - Lint Python code with comprehensive rule set

## Architecture

This is a hybrid TypeScript/Python platform that provides AI and data services for the OpenFn toolchain.

### Server Structure (TypeScript - Bun + Elysia)
- **Entry**: `platform/src/index.ts` → `platform/src/server.ts`
- **Framework**: Elysia web framework running on Bun runtime
- **Middleware**: Health checks, directory listing, Python service bridging
- **Services Bridge**: `/services/<name>` endpoints invoke Python modules via child processes

### Python Services Architecture
- **Entry Point**: `services/entry.py` - All Python services invoked through this module
- **Service Structure**: Each service is a Python module in `services/<name>/` with a `main()` function
- **Invocation Pattern**: `services/<name>/<name>.py` with `main(data: dict) -> dict`
- **Context Isolation**: Each service call runs in its own process context

### Key Python Services

#### AI & Generation Services
- `job_chat/` - AI chatbot for OpenFn job assistance with RAG
- `workflow_chat/` - AI assistant for OpenFn workflow creation
- `adaptor_gen/` - AI-powered OpenFn adaptor generation
- `code_generator/` - General-purpose code generation service
- `gen_job/` - Generates OpenFn job code
- `describe_adaptor/` - Generates descriptions for OpenFn adaptors
- `signature_generator/` - Generates function signatures for adaptors
- `inference/` - ML model inference (supports multiple models)

#### Embeddings & Search Services
- `embeddings/` - Vector embeddings with Pinecone (production index: "apollo-mappings")
- `search_docsite/` - Searches OpenFn documentation using Pinecone vector store
- `vocab_mapper/` - Maps medical vocabularies (LOINC/SNOMED) using embeddings
- `embed_docsite/` - Indexes OpenFn documentation for search
- `embed_loinc_dataset/` - Preprocesses and embeds LOINC medical codes
- `embed_snomed_dataset/` - Preprocesses and embeds SNOMED medical terminology

#### Utility Services
- `latest_adaptors/` - Retrieves latest adaptor versions
- `status/` - System health and status checks

### Communication Protocols
- **HTTP**: POST requests with JSON payloads
- **WebSocket**: Same URLs as HTTP, provides live log streaming
  - `start` event: Client sends JSON payload
  - `log` event: Server streams Python logger output (not print statements)
  - `complete` event: Server sends final JSON result

### Python Environment
- **Python Version**: 3.11 (exact requirement)
- **Dependency Management**: Poetry with in-project `.venv`
- **Environment Loading**: Uses `.env` file for API keys and configuration
- **Error Handling**: Custom `ApolloError` class with Sentry integration

### Development Patterns
- TypeScript services are minimal - primarily routing and Python process management
- Python services follow common patterns but have no strict interface beyond `main(data) -> dict`
- All services expect and return JSON
- Logger output (not print statements) streams to WebSocket clients
- API keys loaded from `.env` rather than embedded in payloads

## Important Notes

### Environment Requirements
- **Required API Keys**: OpenAI API key, Pinecone API key (for embedding services)
- **Python Environment**: Must use Python 3.11 exactly
- **Vector Store**: Production uses Pinecone index "apollo-mappings" with namespace-based collections

### Service Dependencies
- Embedding services use `loinc_store.connect_loinc()` and `snomed_store.connect_snomed()` for production data
- Both connect to Pinecone with "apollo-mappings" index
- Medical vocab services depend on pre-embedded LOINC/SNOMED datasets

### Development Guidelines
- Use `logger` for output that should stream to WebSocket clients (not `print`)
- Service entry points must be named `<service_name>.py` with `main(data: dict) -> dict`
- Test services locally with `bun py <service> <input.json>`
- Vector store supports both Pinecone and Zilliz but production uses Pinecone only