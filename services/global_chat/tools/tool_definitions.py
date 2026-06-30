"""
Tool definitions for the supervisor agent.

These are Claude API tool schemas that define what tools are available.
"""

# Tool 1: Search documentation
SEARCH_DOCUMENTATION_TOOL = {
    "name": "search_documentation",
    "description": """Search OpenFn documentation using semantic similarity.
Use this when you need to find general information about OpenFn and its automation concepts to help answer the user's question.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query describing what you need to find"
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5
            }
        },
        "required": ["query"]
    }
}

# Tool 2: Call workflow agent
CALL_WORKFLOW_AGENT_TOOL = {
    "name": "call_workflow_agent",
    "description": """Create or modify workflow STRUCTURE (YAML): which steps/jobs exist, their names, adaptors, triggers, and edges (the flow between steps).

Use for: adding, removing, renaming, or reordering steps; changing adaptors or triggers; editing the flow/edges between steps; fixing YAML structure errors.

CANNOT read or edit the code inside a step (its `body` / expression). To write or change step code — even the same change across many steps — use call_job_code_agent, never this tool.

The current workflow YAML is passed automatically. Do NOT include YAML in your message.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message for the workflow_agent with relevant context"
            }
        },
        "required": ["message"]
    }
}

# Tool 3: Call job code agent
CALL_JOB_CODE_AGENT_TOOL = {
    "name": "call_job_code_agent",
    "description": """Write or edit the code inside a step (its JavaScript `body` / adaptor expression). This is the ONLY tool that can read or change step code.

Edits ONE step per call — set job_key to that step. To make a code change across N steps, make N calls (they may run in parallel). The step must already exist in the workflow YAML — call call_workflow_agent first if it doesn't.

Describe the goal in plain language; the job code agent is the expert on adaptor functions and will choose the implementation.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message for the job code agent with relevant context"
            },
            "job_key": {
                "type": "string",
                "description": "The key of the job in the workflow YAML to write or edit code for (e.g. 'fetch-patients'). When provided, the existing job body is extracted from the workflow YAML and passed to the job code agent as the current code to edit."
            }
        },
        "required": ["message"]
    },
    "cache_control": {"type": "ephemeral"}
}

# Tool 4: Inspect job code
INSPECT_JOB_CODE_TOOL = {
    "name": "inspect_job_code",
    "description": """Read the current code body of one or more jobs in the workflow (read-only).

Use this to inspect existing step code before editing — e.g. to find which steps a change applies to before editing only those, or to base one step on another. Pass all the job keys you need in a single call rather than calling once per job.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The job keys to inspect (e.g. ['fetch-patients', 'load-dhis2'])"
            }
        },
        "required": ["job_keys"]
    }
}

# Export all tool definitions
TOOL_DEFINITIONS = [
    SEARCH_DOCUMENTATION_TOOL,
    CALL_WORKFLOW_AGENT_TOOL,
    CALL_JOB_CODE_AGENT_TOOL,
    INSPECT_JOB_CODE_TOOL
]
