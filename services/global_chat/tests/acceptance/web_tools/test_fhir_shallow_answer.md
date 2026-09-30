---
id: global-chat.web-tools.fhir-shallow-answer
service: global_chat
judges: [general]
---

# notes

The user asks a factual question about the FHIR R4 Patient resource with web search enabled. hl7.org is on the planner's allowlist, so the planner should look it up in the published R4 spec and answer from it. The point of this spec is how the answer uses fetched content.

# quality_criteria

- States that each Patient.contact must contain at least a contact's details (a name, telecom or address) or a reference to an organization.
- Mentions that this is a formal constraint in the spec (the pat-1 invariant), or otherwise makes clear it is a rule rather than advice.
- Names the source in prose (the FHIR R4 specification or the hl7.org Patient page).
- Does not pad the answer with unrelated Patient fields.

# settings

## options.web_search

true

## meta.session_id

sess-web-tools-fhir-shallow-0001

# turn

## role

user

## content

In FHIR R4, what rule applies to each entry in Patient.contact? What must it contain at minimum?
