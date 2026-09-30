---
id: global-chat.web-tools.fhir-deep-answer
service: global_chat
judges: [general]
---

# notes

The codes sit past the point where a fetch of the Patient page truncates at the old max_content_tokens, though they also appear on the short FHIR value-set page for link types. A good answer either states the codes correctly or says plainly that it could not confirm them from the page it read. Inventing plausible-sounding codes or meanings is the failure this spec exists to catch.

# quality_criteria

- Lists the four Patient.link.type codes (replaced-by, replaces, refer, seealso) with a correct one-line meaning for each, or, if it could not confirm them, says so explicitly rather than guessing.
- Names the source in prose.
- If it says anything was not confirmed, it is specific about what.

# settings

## options.web_search

true

## meta.session_id

sess-web-tools-fhir-deep-0001

# turn

## role

user

## content

In FHIR R4, what codes can Patient.link.type take, and what does each mean?
