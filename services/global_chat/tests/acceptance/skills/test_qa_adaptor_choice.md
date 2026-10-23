---
id: global-chat.skills.qa-adaptor-choice
service: global_chat
judges: [general]
---

# notes

The user runs /qa on a workflow whose second step posts to DHIS2 with the plain
HTTP adaptor, although DHIS2 has its own adaptor. The planner has no adaptor
list of its own, so this tests that /qa's review by the workflow agent catches
the choice. /qa reports and changes nothing until the user asks.

# quality_criteria

- The reply recommends the DHIS2 adaptor for the step that posts to DHIS2, rather than plain HTTP.
- No job code or workflow YAML is changed; the reply proposes changes rather than making them.

# settings

## page

workflows/visit-sync

## skill

```json
{"name": "qa"}
```

## workflow_yaml

```yaml
name: visit-sync
jobs:
  fetch-visits:
    id: job-fetch-visits-id
    name: Fetch visits
    adaptor: "@openfn/language-http@7.0.0"
    body: |
      get('https://clinic.example.org/api/visits');
      fn(state => ({ ...state, visits: state.data.visits }));
  send-to-dhis2:
    id: job-send-to-dhis2-id
    name: Send to DHIS2
    adaptor: "@openfn/language-http@7.0.0"
    body: |
      each(
        $.visits,
        post('https://dhis2.example.org/api/events', state => ({
          program: 'eBAghkXzQGu',
          orgUnit: state.data.facilityId,
          eventDate: state.data.date,
          status: 'COMPLETED',
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 3 * * *"
    enabled: true
edges:
  cron->fetch-visits:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-visits
    condition_type: always
    enabled: true
  fetch-visits->send-to-dhis2:
    id: edge-fetch-send
    source_job: fetch-visits
    target_job: send-to-dhis2
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-skills-qa-adaptor-choice-0001

# turn

## role

user

## content

/qa can you check this before we turn it on for all clinics?
