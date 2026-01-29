"""
Tool definitions for the supervisor agent.

These are Claude API tool schemas that define what tools are available.
"""

# Tool 1: Search documentation
SEARCH_DOCUMENTATION_TOOL = {
    "name": "search_documentation",
    "description": """Search OpenFn documentation using semantic similarity.
Use this when you need to find information about OpenFn adaptors, functions,
or workflow concepts to help answer the user's question.""",
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
- Generate a new workflow from scratch
- Add jobs, steps, or triggers to an existing workflow
- Modify workflow structure or configuration
- Debug or fix workflow YAML errors

You can either:
1. Pass the user's message directly (mode: 'pass_through') - use when the user's
   request is clear and doesn't need rephrasing. You will directly return the
   workflow_agent's response with minimal processing (token-efficient).
2. Write a custom message for the workflow_agent (mode: 'custom_message') - use when
   you need to break down the task or provide specific instructions. You will
   synthesize the workflow_agent's response in your own words.

CRITICAL: If there is a YAML workflow attached, it will be automatically passed
to the workflow_agent. Do NOT include YAML in your message - it will be handled separately.

IMPORTANT: When workflow_agent returns YAML, you MUST include it in your final
response to the user. Never forget to return the YAML output.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["pass_through", "custom_message"],
                "description": "How to communicate with the workflow_agent and handle the response"
            },
            "message": {
                "type": "string",
                "description": "Custom message for the workflow_agent (required if mode is custom_message)"
            },
            "copy_response": {
                "type": "boolean",
                "description": "If true, return workflow_agent's exact response without modification. Only valid with pass_through mode. Use to save tokens when no synthesis needed.",
                "default": False
            }
        },
        "required": ["mode"]
    }
}

# Export all tool definitions
TOOL_DEFINITIONS = [
    SEARCH_DOCUMENTATION_TOOL,
    CALL_WORKFLOW_AGENT_TOOL
]
