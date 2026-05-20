---
id: global-chat.vague-gmail-to-database
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Vague request: "fetch my data from gmail and send it to my database". No specifics on which gmail data, which database, how to map between them. The planner should surface the ambiguity (or ask clarifying questions) rather than silently inventing details.

# quality_criteria

- The response surfaces the ambiguities in the user's request (e.g. which gmail data, which database, how to authenticate) rather than silently inventing unstated requirements.
- If the response asks clarifying questions, they are concrete and answerable, not generic.

# turn

## role

user

## content

I want to fetch my data from gmail and send it to my database
