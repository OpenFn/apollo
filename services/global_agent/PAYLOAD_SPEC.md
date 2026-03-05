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

  "user": {} ,                            // User metadata (optional, reserved for future use)

  "history": [                            // Chat history (optional)
    {
      "role": "user|assistant",
      "content": "string"
    }
  ],

  "options": {                            // Runtime options (optional)
    "stream": false
  },

  "api_key": "string (optional)"
}
```

### Field Descriptions

- **`content`** (string, required): The user's message or query.

- **`workflow_yaml`** (string, optional): The full workflow YAML, including all job bodies. This is the single source of truth for both workflow structure and job code. The backend returns an updated version of this after each turn.

- **`page`** (string, optional): The current page URL. Used for routing decisions and for identifying the focused job when on a step page.
  - `workflows/<name>/<step-name>` — user is viewing a specific job step
  - `workflows/<name>` — user is viewing the workflow overview
  - `workflows/<name>/settings` — user is viewing workflow settings

- **`user`** (object, optional): User metadata. Reserved for future use.

- **`history`** (array, optional): Conversation history. Each turn has `role` and `content`. History is managed and returned by each agent internally.

- **`options`** (object, optional): Runtime options.
  - **`stream`** (boolean): Enable streaming response (default: false).

- **`api_key`** (string, optional): Override API key for this request.

---

## Output Payload

```json
{
  "response": "string",                  // Main text response

  "workflow_yaml": "string|null",        // Full workflow YAML (null if no YAML change this turn)

  "history": [                           // Conversation history including this turn
    {
      "role": "user|assistant",
      "content": "string"
    }
  ],

  "usage": {                             // Token usage
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },

  "meta": {                              // Execution metadata
    "agents": ["router", "workflow_agent"],
    "router_confidence": 5,
    "planner_iterations": 2              // Only present for planner path
  }
}
```

### Field Descriptions

- **`response`** (string): The main text response from the agent.

- **`workflow_yaml`** (string or null): The updated full workflow YAML. The frontend diffs this against the previously sent YAML to show the user what changed. `null` if the turn produced no YAML update (e.g. a read-only or purely informational response).

- **`history`** (array): Updated conversation history including the latest exchange.

- **`usage`** (object): Token usage across all agents invoked.

- **`meta`** (object): Execution metadata.
  - **`agents`** (array): Ordered list of agents invoked (e.g. `["router", "workflow_agent"]`).
  - **`router_confidence`** (number): Router's confidence score (1–5).
  - **`planner_iterations`** (number): Number of tool-calling iterations (planner path only).

---

## Page URL → Routing Behaviour

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
  "history": [],
  "options": { "stream": false }
}
```

**Output:**
```json
{
  "response": "I've added error handling to the Fetch Data job...",
  "workflow_yaml": "name: My Workflow\njobs:\n  fetch-data:\n    name: Fetch Data\n    adaptor: \"@openfn/language-http@6.0.0\"\n    body: |\n      get('/api/data').catch(err => { ... });\n",
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
  "workflow_yaml": "name: My Workflow\njobs:\n  fetch-data:\n    ...\n  load-dhis2:\n    name: Load to DHIS2\n    adaptor: \"@openfn/language-dhis2@...\"\n    body: |\n      // Add operations here\n",
  "history": [...],
  "usage": { ... },
  "meta": { "agents": ["router", "workflow_agent"], "router_confidence": 5 }
}
```

---

## Design Principles

1. **Single YAML source of truth**: `workflow_yaml` always contains the complete workflow including job bodies. The frontend diffs it to show changes.
2. **Page-driven routing**: The `page` URL tells the router what the user is focused on, avoiding ambiguous name matching.
3. **Transparent execution**: `meta.agents` shows the full execution path.
4. **Usage tracking**: Token usage is aggregated across all agents invoked in a single request.

### Note on job code stitching (planner path)

When the planner generates a complete new workflow (structure + job code for multiple steps), the current implementation returns the workflow structure only — job bodies will contain `// Add operations here` placeholders. Full code stitching from planner job_agent calls into the YAML is deferred.
