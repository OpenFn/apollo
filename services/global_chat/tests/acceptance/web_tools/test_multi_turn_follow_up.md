---
id: global-chat.web-tools.multi-turn-follow-up
service: global_chat
judges: [general]
---

# notes

Third turn of a conversation about FHIR R4 Patient contact fields. The earlier assistant answers already established the relevant fields (telecom as ContactPoint 0..*, address 0..*, contact 0..*). The follow-up should build on them rather than restarting, and the mapping should use Patient.telecom with system "phone".

# quality_criteria

- Builds on the earlier answers rather than re-explaining the Patient resource from scratch.
- Maps the phone number into Patient.telecom as a ContactPoint with system "phone" and the number in value.
- Mentions that telecom is a list (0..*), so the number goes in as an array entry.
- Does not generate a workflow or job code attachment. Describing the mapping in text with an inline snippet is fine.

# settings

## options.web_search

true

## meta.session_id

sess-web-tools-multi-turn-0001

# history

## turn

### role

user

### content

Which fields does a FHIR R4 Patient have for contact information?

## turn

### role

assistant

### content

From the FHIR R4 Patient page (hl7.org/fhir/R4/patient.html): `telecom` (ContactPoint, 0..*) holds phone numbers, emails and similar; `address` (Address, 0..*) holds postal addresses; and `contact` (BackboneElement, 0..*) holds contact parties such as next of kin, each with their own name, telecom and address.

## turn

### role

user

### content

Which of those fields can repeat?

## turn

### role

assistant

### content

All three repeat: `telecom`, `address` and `contact` are each 0..* on Patient, so a patient can have several phone numbers, several addresses and several contact parties.

# turn

## role

user

## content

How would I map a CommCare phone number into it?
