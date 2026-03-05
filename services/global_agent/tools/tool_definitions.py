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
    "description": """Create or modify OpenFn workflows (YAML).

Use this tool when the user wants to:
- Do anything related to workflows
- Add jobs, steps, or triggers to an existing workflow or create a new workflow from scratch
- Modify workflow structure or configuration
- Debug or fix workflow YAML errors

Write a clear message for the workflow_agent. Include any relevant conversation
context that the agent needs to understand the request.

The current workflow YAML is automatically passed to the workflow_agent.
Do NOT include YAML in your message.""",
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
    "description": """Get help with OpenFn job code (JavaScript expressions for individual steps).

OpenFn workflows define high-level orchestration (triggers, jobs, edges). Job code defines what
each step actually does using adaptor functions. Use this tool for:
- Writing job expressions using adaptor functions (e.g., create(), upsert(), get())
- Understanding adaptor-specific syntax and parameters
- Debugging job code errors
- Getting code examples for specific adaptors

Write a clear message for the job code agent. Include any relevant conversation
context that the agent needs to understand the request.

The agent has access to adaptor documentation and will provide code examples.""",
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
    "description": """Read the current code body of a specific job in the workflow (read-only).

Use this when you need to see existing job code before writing code for another job,
for example when the user asks to make one step similar to another.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_key": {
                "type": "string",
                "description": "The job key to inspect (e.g. 'fetch-patients')"
            }
        },
        "required": ["job_key"]
    }
}

# Export all tool definitions
TOOL_DEFINITIONS = [
    SEARCH_DOCUMENTATION_TOOL,
    CALL_WORKFLOW_AGENT_TOOL,
    CALL_JOB_CODE_AGENT_TOOL,
    INSPECT_JOB_CODE_TOOL
]
