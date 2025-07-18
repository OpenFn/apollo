# apollo

## 0.13.2

### Patch Changes

- job_chat: Fix an issue where the model would ignore user logs

### Patch Changes

## 0.13.1

### Patch Changes

- 7b48834: workflow_chat: preserve UUIDs during workflow generation

## 0.13.0

### Minor Changes

- b98bfab: add updated adaptor fetching

## 0.12.0

### Minor Changes

- 4f5a5f2: allow ai edits of existing workflows

### Patch Changes

- 2776d4d: update token limit for job chat

## 0.11.4

### Patch Changes

- bdc0daf: improve prompt for workflow generation

## 0.11.3

### Patch Changes

- a3119a3: Override workflow generation yaml body key to be empty
- 1159eeb: fix workflow gen variable scope

## 0.11.2

### Patch Changes

- workflow_chat: update adaptor list

## 0.11.1

### Patch Changes

- Ensure the user's API key is used for rag search

## 0.11.0

### Minor Changes

- bae48d3: Add workflow_chat service

## 0.10.0

### Minor Changes

- 6f88248: Integrate docsite rag for the AI assistant

## 0.9.2

### Patch Changes

- aef476d: Update claude model from 3.5 to 3.7

## 0.9.1

### Patch Changes

- job_chat: update Claude to 3.7

## 0.9.0

### Minor Changes

- c0e391c: Add new docsite rag
- 14c149d: Add a `/status` endpoint which returns the status of server-managed
  API keys

## 0.8.0

### Minor Changes

- a03bbea: vocab mapper: Add batching

### Patch Changes

- 1d824ba: job_chat: Update the AI Assistant prompt to be more concise, secure,
  and context-aware
- 960dffb: job_chat: add basic prompt support for collections

## 0.7.2

### Patch Changes

- ob_chat: Fix dependencies
- vocab_mapper: Fix production key loading

## 0.7.1

### Patch Changes

- Bump dependencies

## 0.7.0

### Minor Changes

- ed5ff26: Add vocab mapper service

### Patch Changes

- ef9f9d2: Add version number to the service listing and healthcheck

## 0.6.0

### Minor Changes

- 032f387: Added embeddings service

## 0.5.3

### Patch Changes

- job-chat: return standardised and detailed error messages

## 0.5.2

### Patch Changes

- Improve job_chat prompt to be less strict about talking about non-job-related
  stuff (eg, it's a lot more willing to discuss adaptors and integrations"

## 0.5.1

### Patch Changes

- Temporarily disable embeddings in build (search is disabled anyway)

## 0.5.0

### Minor Changes

- 73096a0: Added project generator
- d3da3cb: Add job generator service
- 013506f: Added search service (RAG)

## 0.4.1

### Patch Changes

- job chat: fix formatting issue

## 0.4.0

### Minor Changes

- 4c8c7eb: use Claude for job_chat

## 0.3.2

### Patch Changes

- chat: de-emphasise each in the prompt

## 0.3.1

### Patch Changes

- job_chat: tweak prompt for better performance

## 0.3.0

### Minor Changes

- 5fa089b: - Support Typescript services
  - Add describe_adaptor service
  - Add job_chat service

## 0.2.0

### Minor Changes

- Use child processes to run python scripts
- add websocket connection with streaming logs
