# global_chat Service

The Global Agent is a supervisor/orchestrator service that routes user requests
to the appropriate subagents and coordinates complex multi-step OpenFn
automation tasks.

It acts as the single entry point for AI assistance in the OpenFn platform,
dispatching to `workflow_chat` (for workflow YAML generation), `job_chat` (for
job code), or a `PlannerAgent` that orchestrates both in sequence.

## Usage

```bash
bun py global_chat --input tmp/payload.json
```

Or via curl:

```bash
curl -X POST https://apollo-staging.openfn.org/services/global_chat --json @tmp/payload.json
```

### Example Input

Simple request on a workflow step page:

```json
{
  "content": "Add error handling to this job",
  "page": "workflows/my-workflow/fetch-data",
  "workflow_yaml": "name: my-workflow\njobs:\n  fetch-data:\n    name: Fetch Data\n    adaptor: '@openfn/language-http@latest'\n    body: '| get(\"/patients\");'\n...",
  "history": []
}
```

Request to build a new multi-step workflow from scratch:

```json
{
  "content": "Create a workflow that fetches patient data from CommCare and loads it to DHIS2"
}
```

**Request Parameters:**

- `content` (required): The user's message or instruction
- `workflow_yaml` (optional): Full workflow YAML including all job bodies; acts
  as the single source of truth for current state
- `page` (optional): Current page URL for routing context —
  `workflows/<name>/<step-name>` routes to job code agent, `workflows/<name>`
  routes to workflow agent
- `history` (optional, default: `[]`): Array of previous conversation turns
  `{role, content}`
- `attachments` (optional): List of input context objects with `type` (e.g.
  `"log"`, `"input_dataclip"`, `"run_output"`) and `content`
- `options` (optional): Runtime options object (e.g. `{stream: false}`)
- `api_key` (optional): Anthropic API key; falls back to `ANTHROPIC_API_KEY` env
  var

### Example Output

```json
{
  "response": "I've created a workflow that fetches patient data from CommCare and loads it to DHIS2. The first job retrieves patient records via the CommCare REST API, and the second job maps and uploads them to DHIS2.",
  "attachments": [
    {
      "type": "workflow_yaml",
      "content": "name: commcare-to-dhis2\njobs:\n  fetch-from-commcare:\n    name: Fetch from CommCare\n    adaptor: '@openfn/language-http@latest'\n    body: '| get(\"/api/v0.5/case/\", ...);'\n  load-to-dhis2:\n    name: Load to DHIS2\n    adaptor: '@openfn/language-dhis2@latest'\n    body: '| upsert(\"trackedEntityInstances\", ...);'\n..."
    }
  ],
  "history": [
    {
      "role": "user",
      "content": "Create a workflow that fetches patient data from CommCare and loads it to DHIS2"
    },
    { "role": "assistant", "content": "I've created a workflow..." }
  ],
  "usage": {
    "input_tokens": 4821,
    "output_tokens": 612,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 3200
  },
  "meta": {
    "agents": [
      "router",
      "planner",
      "workflow_agent",
      "job_code_agent",
      "job_code_agent"
    ],
    "router_confidence": 4,
    "planner_iterations": 3,
    "total_tool_calls": 3
  }
}
```

**Response Fields:**

- `response`: The assistant's text response to the user
- `attachments`: Artifacts produced — currently always
  `{type: "workflow_yaml", content: string}` when YAML was generated or modified
- `history`: Updated conversation history including the latest exchange
- `usage`: Aggregated token usage across all agents called during the request
- `meta.agents`: Ordered list of agents invoked (e.g.
  `["router", "workflow_agent"]` or
  `["router", "planner", "workflow_agent", "job_code_agent"]`)
- `meta.router_confidence`: Router's confidence in its routing decision (1–5)
- `meta.planner_iterations` (planner path only): Number of tool-calling loop
  iterations
- `meta.total_tool_calls` (planner path only): Total tool calls made by the
  planner

## Implementation

### Routing

Every request first passes through the `RouterAgent` (Claude Haiku), which
examines the user's message, current page, and existing YAML to decide where to
send it:

- **`workflow_agent`** — request is about workflow structure (triggers, jobs,
  edges, scheduling)
- **`job_code_agent`** — request is about job code, or the current page is a
  step page (`workflows/<name>/<step-name>`)
- **`planner`** — request requires both workflow structure and job code,
  involves multiple sequential operations, or is ambiguous

The router defaults to `planner` when uncertain.

### Direct Routes

For straightforward requests, the router calls subagents directly:

- **workflow_agent path** → calls `workflow_chat` with the user message and
  existing YAML
- **job_code_agent path** → extracts the relevant job from the YAML by step
  name, calls `job_chat` with the job's code and adaptor as context, then
  stitches the returned code back into the YAML

### Planner

For complex requests, the `PlannerAgent` (Claude Sonnet) runs an agentic
tool-calling loop with access to four tools:

- **`call_workflow_agent`** — create or modify workflow YAML structure
- **`call_job_code_agent`** — write or edit job code for a specific job
  (requires an existing workflow with that job defined)
- **`search_documentation`** — semantic search over the OpenFn docsite
- **`inspect_job_code`** — read-only inspection of a job's current code

The planner always calls `call_workflow_agent` first to establish the structure,
then calls `call_job_code_agent` for each job that needs code. Job code is
stitched into the workflow YAML immediately after each call.

The loop continues until the model signals it is done (up to a configurable
maximum of tool calls, default 10).

## Testing

Run the multi-step planner tests with:

```bash
poetry run pytest global_chat/tests/test_planner_multistep.py -v -s
```

Run all tests for the service:

```bash
poetry run pytest global_chat/tests/ -v -s
```
