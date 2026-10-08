---
id: global-chat.skills.design-continues-over-turns
service: global_chat
judges: [general]
---

# notes

The user started /design on the previous turn. Its instructions are in that
turn of the history, exactly as Apollo returned it, and must keep applying now
that the user has answered. The planner's own default is to build a workflow as
soon as the shape is guessable; /design overrides that until the user agrees on
a design. Judge the conversation, not the wording: there are many good ways to
continue a consultation.

# quality_criteria

- The reply continues the design conversation, asking follow-up questions or offering options, and does not build or change a workflow yet.
- It engages with the process the user described, a weekly manual copy of Kobo form data into DHIS2, rather than asking generic questions it could have asked before.
- It asks only a few questions at a time, rather than a long questionnaire.

# settings

## page

workflows/new

## meta.session_id

sess-skills-design-continues-0001

# history

## turn

### role

user

### content

[pg:workflow] <skill name="design">
The user wants to think the design through before anything is built. Treat it
as a consultation: suggest ideas and sketch options freely, but build only
when they're ready.

Find out where they are and meet them there. Some don't yet know what could be
automated or how many workflows it takes; others have the shape and need help
with the details. Follow their lead on how deep to go.

If the user struggles to specify what they want, start from people and process
rather than systems. Wherever the conversation starts, make sure the design
rests on the process it serves, and question requirements against how the
result will be used; the simpler design is often enough. The result is often a mix
of automated steps and steps people keep doing.

Areas to draw on as the conversation needs them, not a list to work through:
- Value: what problem automation solves, what's done by hand today and what it
  costs in time, and what happens if nothing changes. This tells you whether
  and how much to automate.
- Process: who does each step, what depends on what, and what's redundant.
- Access: how each system can be reached (API, webhooks, file exports, direct
  database), what's in the way (hosting, VPN, firewall, IP allowlisting), and
  whether there's a test environment. Suggest getting credentials early so
  access can be tested. If a system or its API is still being built or
  configured, say it may be too early to integrate with it.
- Timing and volume: whether it really needs to be immediate, whether data
  flows one way or both, and how much moves per run, which decides whether API
  limits and paging matter.
- Ownership: who owns each system and its data, and who will run and maintain
  the workflow, how technical they are, and who decides on changes later.
- Data: real sample records from each side, whether records move one to one
  or are summarised, fields the target needs that users never see, and shared
  lists (regions, services) and where they should live.
- Failure: who hears about it, and how a run is redone without duplicates.

Ask a few questions at a time, most consequential first. When there's a real
choice, recommend one option and name the alternative. Prefer the simplest
design that meets the need, and say when an idea goes beyond what was asked.

Flag details that rest on assumptions or documentation and still need
checking, and help the user see how to check them, without holding up the
design. If you're unsure how the platform behaves, say so rather than design
around a guess. Note open decisions and who can answer each rather than
filling them in.

When the design is agreed, summarise it at the level of detail you reached, in
a form the user could share with the people who need to agree to it, with any
open decisions. Then offer to build it.
</skill>

The user invoked /design.

I want to automate something with our clinic data but I'm not sure what yet

## turn

### role

assistant

### content

Happy to help you figure this out. Let's start from how your clinic actually works, not the tech.

A few questions to get oriented:

1. **What's painful right now?** Where does someone on your team spend time copying data between systems, re-typing things, chasing reports, or reconciling records by hand? That's usually where automation pays off first.

2. **What systems hold your clinic data?** For example an EMR/EHR (OpenMRS, DHIS2, CommCare, Bahmni, a custom system?), a spreadsheet, a lab system, a billing tool, an SMS service? Even a rough list helps.

3. **Who are you reporting to or sharing data with?** Many clinics have to send aggregate numbers to a ministry/DHIS2, sync patient records somewhere, or send reminders to patients. Is anything like that part of your world?

You don't need precise answers — just tell me what a typical frustrating task looks like, and we'll trace it back to what could be automated.

# turn

## role

user

## content

Our nurses fill in a KoboToolbox form for every patient visit, and every Friday someone copies the totals into DHIS2 by hand. It takes most of the afternoon.
