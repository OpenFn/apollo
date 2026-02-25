# Global Agent Payload Specification

This document defines the input and output payload structure for the Global Agent (Supervisor Agent) service.

## Input Payload

```JSON
{
  "content": "string (REQUIRED)",        // User message

  "context": {                           // All contextual information
    "workflow_yaml": "string (optional)", // Current workflow YAML
    "job_code": {                        // Job code context (optional)
      "expression": "string",
      "page_name": "string",
      "adaptor": "string"
    },
    "errors": "string (optional)"        // Error context
  },

  "history": [                           // Chat history (optional)
    {
      "role": "user|assistant",
      "content": "string",
      "attachments": []
    }
  ],

  "stream": false,
  "read_only": false,
  "api_key": "string (optional)"
}
```

### Field Descriptions

#### Required Fields
- **`content`** (string): The user's message or query

#### Optional Fields
- **`context`** (object): Contextual information for the request
  - **`workflow_yaml`** (string): Current workflow YAML definition
  - **`job_code`** (object): Job code context
    - **`expression`** (string): The job expression/code
    - **`page_name`** (string): The page/job name
    - **`adaptor`** (string): The adaptor being used
  - **`errors`** (string): Error messages or context

- **`history`** (array): Conversation history
  - **`role`** (string): Either "user" or "assistant"
  - **`content`** (string): Message content
  - **`attachments`** (array): Attachments from previous responses

- **`stream`** (boolean): Enable streaming response (default: false)
- **`read_only`** (boolean): Read-only mode - no code generation (default: false)
- **`api_key`** (string): Override API key for this request

---

## Output Payload

```JSON
{
  "response": "string",                  // Main text response

  "attachments": [                       // Output attachments
    {
      "type": "workflow_yaml|job_code|document|link",
      "content": "string"
    }
  ],

  "history": [                           // Updated conversation history
    {
      "role": "user|assistant",
      "content": "string",
      "attachments": []
    }
  ],

  "usage": {                             // Token usage (4 fields)
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },

  "meta": {                              // Execution metadata
    "agents": ["router", "planner", "workflow_agent"],  // Execution chain
    "router_confidence": 5,              // Optional details
    "planner_iterations": 2
  }
}
```

### Field Descriptions

#### Required Fields
- **`response`** (string): The main text response from the agent
- **`attachments`** (array): Generated attachments
  - **`type`** (string): Type of attachment - one of:
    - `workflow_yaml`: Workflow YAML definition
    - `job_code`: Job expression/code
    - `document`: Documentation or text document
    - `link`: URL or reference link
  - **`content`** (string): The attachment content

- **`history`** (array): Updated conversation history including the latest exchange
  - **`role`** (string): Either "user" or "assistant"
  - **`content`** (string): Message content
  - **`attachments`** (array): Attachments from this turn

- **`usage`** (object): Token usage information
  - **`input_tokens`** (number): Input tokens consumed
  - **`output_tokens`** (number): Output tokens generated
  - **`cache_creation_input_tokens`** (number): Tokens used for cache creation
  - **`cache_read_input_tokens`** (number): Tokens read from cache

- **`meta`** (object): Execution metadata
  - **`agents`** (array of strings): Ordered list of agents invoked during execution (e.g., `["router", "planner", "workflow_agent"]`)
  - **`router_confidence`** (number, optional): Router's confidence score (1-5)
  - **`planner_iterations`** (number, optional): Number of planning iterations
  - Additional agent-specific metadata may be included

---

## Examples

### Simple Workflow Request

**Input:**
```json
{
  "content": "Create a workflow that fetches data from CommCare",
  "context": {},
  "history": []
}
```

**Output:**
```json
{
  "response": "I've created a workflow that fetches data from CommCare...",
  "attachments": [
    {
      "type": "workflow_yaml",
      "content": "name: Fetch CommCare Data\njobs:\n  fetch:\n    ..."
    }
  ],
  "history": [
    {
      "role": "user",
      "content": "Create a workflow that fetches data from CommCare",
      "attachments": []
    },
    {
      "role": "assistant",
      "content": "I've created a workflow that fetches data from CommCare...",
      "attachments": [
        {
          "type": "workflow_yaml",
          "content": "name: Fetch CommCare Data\njobs:\n  fetch:\n    ..."
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "meta": {
    "agents": ["router", "workflow_agent"],
    "router_confidence": 5
  }
}
```

### Job Code Help with Context

**Input:**
```json
{
  "content": "How do I filter this data?",
  "context": {
    "job_code": {
      "expression": "fn(state => state.data)",
      "page_name": "Process Data",
      "adaptor": "@openfn/language-common@2.0.0"
    }
  },
  "history": []
}
```

**Output:**
```json
{
  "response": "You can filter the data using the `each` function...",
  "attachments": [
    {
      "type": "job_code",
      "content": "fn(state => {\n  const filtered = state.data.filter(item => item.status === 'active');\n  return { ...state, filtered };\n});"
    }
  ],
  "history": [
    {
      "role": "user",
      "content": "How do I filter this data?",
      "attachments": []
    },
    {
      "role": "assistant",
      "content": "You can filter the data using the `each` function...",
      "attachments": [
        {
          "type": "job_code",
          "content": "fn(state => {\n  const filtered = state.data.filter(item => item.status === 'active');\n  return { ...state, filtered };\n});"
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 890,
    "output_tokens": 234,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 450
  },
  "meta": {
    "agents": ["router", "job_code_agent"],
    "router_confidence": 5
  }
}
```

### Complex Multi-Agent Request

**Input:**
```json
{
  "content": "Create a complete integration from DHIS2 to OpenMRS with error handling",
  "context": {},
  "history": []
}
```

**Output:**
```json
{
  "response": "I've created a complete integration workflow with three jobs...",
  "attachments": [
    {
      "type": "workflow_yaml",
      "content": "name: DHIS2 to OpenMRS Integration\njobs:\n  fetch:\n    ..."
    },
    {
      "type": "document",
      "content": "# Integration Guide\n\nThis workflow includes:\n1. Fetching data from DHIS2\n2. Transforming data\n3. Loading to OpenMRS\n..."
    }
  ],
  "history": [
    {
      "role": "user",
      "content": "Create a complete integration from DHIS2 to OpenMRS with error handling",
      "attachments": []
    },
    {
      "role": "assistant",
      "content": "I've created a complete integration workflow with three jobs...",
      "attachments": [
        {
          "type": "workflow_yaml",
          "content": "name: DHIS2 to OpenMRS Integration\njobs:\n  fetch:\n    ..."
        },
        {
          "type": "document",
          "content": "# Integration Guide\n\nThis workflow includes:\n1. Fetching data from DHIS2\n2. Transforming data\n3. Loading to OpenMRS\n..."
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 2345,
    "output_tokens": 1890,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 500
  },
  "meta": {
    "agents": ["router", "planner", "workflow_agent", "doc_agent"],
    "router_confidence": 4,
    "planner_iterations": 3
  }
}
```

---

## Design Principles

1. **Extensibility**: The `attachments` array can accommodate new attachment types without breaking changes
2. **Simplicity**: Top-level flags (stream, read_only) rather than nested options object
3. **Transparency**: The `meta.agents` array shows the complete execution path
4. **Context Consolidation**: All contextual information grouped under `context`
5. **Usage Tracking**: Complete token usage including cache metrics
