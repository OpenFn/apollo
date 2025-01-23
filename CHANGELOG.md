# apollo

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
