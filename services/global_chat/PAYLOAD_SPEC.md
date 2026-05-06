# Global Agent Payload Specification

This document defines the input and output payload structure for the Global Agent service.

## Input Payload

```json
{
  "content": "string (REQUIRED)",         // User message

  "workflow_yaml": "string (optional)",   // Full workflow YAML including all job bodies

  "page": "string (optional)",            // Current page URL, e.g.:
                                          //   workflows/my-workflow/fetch-patients
                                          //   workflows/my-workflow
                                          //   workflows/my-workflow/settings

  "meta": {                                // Optional metadata
    "session_id": "string",              //   Session ID for multi-turn grouping
    "user": {                            //   User identity for Langfuse attribution
      "id": "string",                    //     User UUID
      "persona": "string"                //     e.g. "core-contributor" | "user"
    }
  },

  "metrics_opt_in": false,                // If true, enable Langfuse tracing for this session

  "history": [                            // Chat history (optional)
    {
      "role": "user|assistant",
      "content": "string"
    }
  ],

  "attachments": [                        // Input attachments (optional)
    {
      "type": "string",                   //   e.g. "log", "input_dataclip", "output_dataclip", "run_input", "run_output"
      "content": "string"                 //   The attachment content
    }
  ],

  "options": {                            // Runtime options (optional)
    "stream": false
  },

  "api_key": "string (REQUIRED in production, optional in development)"
}
```

### Field Descriptions

- **`content`** (string, required): The user's message or query.

- **`workflow_yaml`** (string, optional): The full workflow YAML, including all job bodies. This is the single source of truth for both workflow structure and job code. The backend returns an updated version of this after each turn.

- **`page`** (string, optional): The current page URL. Used for routing decisions and for identifying the focused job when on a step page.
  - `workflows/<name>/<step-name>` — user is viewing a specific job step
  - `workflows/<name>` — user is viewing the workflow overview
  - `workflows/<name>/settings` — user is viewing workflow settings

- **`meta`** (object, optional): Extensible metadata object.
  - **`session_id`** (string, optional): Session ID for grouping multi-turn conversations.
  - **`user`** (object, optional): User identity. `id` (string) and `persona` (string, e.g. `"core-contributor"` or `"user"`). Attributed to Langfuse traces when tracking is enabled.

- **`metrics_opt_in`** (boolean, optional): If `true`, enables Langfuse tracing for this session. The frontend is responsible for setting this; the backend tracks if and only if this flag is `true`.

- **`history`** (array, optional): Conversation history. Each turn has `role` and `content`. History is managed and returned by each agent internally.

- **`attachments`** (array, optional): Input attachments providing additional context for the request. Each entry has a `type` and `content` field. Useful for passing logs, dataclips, run inputs/outputs, or other contextual data that the agent can use when processing the request. Currently supported types:
  - `log` — execution logs from a run
  - `input_dataclip` — input data for a step
  - `output_dataclip` — output data from a step
  - `run_input` — input payload for the whole run
  - `run_output` — final output of a run

- **`options`** (object, optional): Runtime options.
  - **`stream`** (boolean): Enable streaming response (default: false).

- **`api_key`** (string, **required in production**, optional in development): API key for the Anthropic API. In production environments this field is required and requests without it will be rejected. In development, the server falls back to the `ANTHROPIC_API_KEY` environment variable if this field is omitted.

---

## Output Payload

```json
{
  "response": "string",                  // Main text response

  "attachments": [                       // Artifacts produced this turn
    {
      "type": "workflow_yaml",           // Attachment type
      "content": "string"               // The artifact content
    }
  ],

  "history": [                           // Conversation history including this turn
    {
      "role": "user|assistant",
      "content": "string | array"        // string for direct routes; array of content
    }                                    // blocks (text, tool_use, tool_result) for planner path
  ],

  "usage": {                             // Token usage (aggregated across all agents)
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },

  "meta": {                              // Execution metadata
    "agents": ["router", "workflow_agent"],
    "router_confidence": 5,

    // Planner path only:
    "planner_iterations": 2,
    "tool_calls": [                      // Tools invoked by the planner
      { "tool": "search_documentation", "input": { "query": "..." } },
      { "tool": "call_workflow_agent", "input": { "message": "..." } }
    ],
    "subagent_calls": [],                // Raw sub-agent result dicts (for debugging)
    "total_tool_calls": 2
  }
}
```

### Field Descriptions

- **`response`** (string): The main text response from the agent.

- **`attachments`** (array): Artifacts produced during this turn. Each entry has a `type` and `content` field. An empty list `[]` means no artifacts were produced (e.g. a purely informational response). Currently supported types: `workflow_yaml`, `job_code`. When both are present, `job_code` contains the suggested code for a specific job and `workflow_yaml` contains the full YAML with the code stitched in.

- **`history`** (array): Updated conversation history including the latest exchange. On direct routes (workflow_agent, job_code_agent), each entry has `content` as a string. On the planner path, entries may have `content` as an array of content blocks (`text`, `tool_use`, `tool_result`) — this is the raw Anthropic messages format from the tool-calling loop.

- **`usage`** (object): Token usage aggregated across all agents invoked (router + planner + sub-agents).

- **`meta`** (object): Execution metadata.
  - **`agents`** (array): Ordered list of agents invoked (e.g. `["router", "workflow_agent"]` or `["router", "planner", "workflow_agent", "job_agent"]`).
  - **`router_confidence`** (number): Router's confidence score (1–5).
  - **`planner_iterations`** (number): Number of tool-calling iterations (planner path only).
  - **`tool_calls`** (array): List of `{tool, input}` objects for each tool the planner invoked (planner path only).
  - **`subagent_calls`** (array): Raw sub-agent result dicts including `_call_metadata` (planner path only, useful for debugging).
  - **`total_tool_calls`** (number): Total number of tool calls made by the planner (planner path only).

---

## Page URL Format and Routing Behaviour

The `page` field is a simplified path/breadcrumb representing where the user is in the app. It uses a **3-segment format** with no leading slash:

```
workflows/<workflow-name>/<step-name>
```

The step name should match a job key in the workflow YAML (exact match or normalized — lowercase, non-alphanumeric chars replaced with hyphens). The backend parses the URL by splitting on `/` and reading the 3rd segment as the step name.

| Page URL | Router signal | What happens |
|---|---|---|
| `workflows/x/step-name` | Job step focused | Routes to job_chat; extracts `expression` + `adaptor` from that job in the YAML; stitches updated code back into YAML before returning |
| `workflows/x` | Workflow overview | Routes to workflow_chat; returns updated full YAML |
| `workflows/x/settings` | Workflow settings | Routes to workflow_chat |
| (none) | Unknown | Router uses LLM to decide |

---

## Examples

### Editing job code on a step page

**Input:**
```json
{
  "content": "Add error handling to this job",
  "workflow_yaml": "name: My Workflow\njobs:\n  fetch-data:\n    name: Fetch Data\n    adaptor: \"@openfn/language-http@6.0.0\"\n    body: |\n      get('/api/data');\n",
  "page": "workflows/my-workflow/fetch-data",
  "attachments": [
    {
      "type": "log",
      "content": "ERROR: Request failed with status 500\n  at get('/api/data')"
    }
  ],
  "history": [],
  "options": { "stream": false }
}
```

**Output:**
```json
{
  "response": "I've added error handling to the Fetch Data job...",
  "attachments": [
    {
      "type": "workflow_yaml",
      "content": "name: My Workflow\njobs:\n  fetch-data:\n    name: Fetch Data\n    adaptor: \"@openfn/language-http@6.0.0\"\n    body: |\n      get('/api/data').catch(err => { ... });\n"
    }
  ],
  "history": [...],
  "usage": { "input_tokens": 890, "output_tokens": 234, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 450 },
  "meta": { "agents": ["router", "job_code_agent"], "router_confidence": 5 }
}
```

### Editing workflow structure

**Input:**
```json
{
  "content": "Add a second job that loads the data to DHIS2",
  "workflow_yaml": "name: My Workflow\njobs:\n  fetch-data:\n    ...\n",
  "page": "workflows/my-workflow",
  "history": [],
  "options": { "stream": false }
}
```

**Output:**
```json
{
  "response": "I've added a new Load to DHIS2 job...",
  "attachments": [
    {
      "type": "workflow_yaml",
      "content": "name: My Workflow\njobs:\n  fetch-data:\n    ...\n  load-dhis2:\n    name: Load to DHIS2\n    adaptor: \"@openfn/language-dhis2@...\"\n    body: |\n      // Add operations here\n"
    }
  ],
  "history": [...],
  "usage": { ... },
  "meta": { "agents": ["router", "workflow_agent"], "router_confidence": 5 }
}
```

---

## Design Principles

1. **Attachments carry artifacts**: Output `attachments` contain structured artifacts (currently `workflow_yaml`). The frontend reads the array to find and diff workflow YAML changes. Input `attachments` carry contextual data (logs, dataclips, etc.) that enrich the agent's understanding of the request.
2. **Page-driven routing**: The `page` URL tells the router what the user is focused on, avoiding ambiguous name matching.
3. **Transparent execution**: `meta.agents` shows the full execution path.
4. **Usage tracking**: Token usage is aggregated across all agents invoked in a single request.

### Job code stitching (planner path)

When the planner generates a new workflow, it first calls `call_workflow_agent` to create the structure, then calls `call_job_code_agent` for each job. After each job code call, the generated code is immediately stitched into the workflow YAML via `stitch_job_code()`. The final `workflow_yaml` attachment in the response contains the complete workflow with all job bodies populated.
