---
id: global-chat.job-code.long-history-same-job-code-change
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

A long conversation history entirely about the same job step (build-mailchimp-segment). The user has been asking clarifying questions about how the existing code groups attendees into a Mailchimp segment, and the assistant has been answering. They now ask for a concrete change to that step: only include attendees whose `consent_marketing` flag is true, and tag the segment with the workshop slug. The router should send this to job_code_agent; the conversation history primes the model with the user's earlier intent. The change should be applied to the build-mailchimp-segment step only.

# quality_criteria

- The response produces updated job code for build-mailchimp-segment that filters attendees by `consent_marketing` being truthy before they are added to the segment.
- The updated code attaches/uses a tag derived from the workshop slug (e.g. `${state.workshop.slug}` or a similar field already in state) on the segment members.
- The change is confined to the build-mailchimp-segment body — fetch-attendees-from-eventbrite and sync-segment-to-mailchimp jobs are left unchanged in the returned YAML.

# settings

## page

workflows/eventbrite-mailchimp-followup/build-mailchimp-segment

## workflow_yaml

```yaml
name: eventbrite-mailchimp-followup
jobs:
  fetch-attendees-from-eventbrite:
    id: job-fetch-eb-id
    name: Fetch Attendees from Eventbrite
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('https://www.eventbriteapi.com/v3/events/{eventId}/attendees/', {
        pathParams: { eventId: $.workshop.eventbrite_id }
      });
      fn(state => {
        const attendees = state.data.attendees || [];
        return { ...state, attendees };
      });
  build-mailchimp-segment:
    id: job-build-segment-id
    name: Build Mailchimp Segment
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const members = state.attendees.map(a => ({
          email_address: a.profile.email,
          status: 'subscribed',
          merge_fields: {
            FNAME: a.profile.first_name,
            LNAME: a.profile.last_name
          }
        }));
        return { ...state, members };
      });
  sync-segment-to-mailchimp:
    id: job-sync-mc-id
    name: Sync Segment to Mailchimp
    adaptor: "@openfn/language-mailchimp@4.0.4"
    body: |
      each(
        $.members,
        upsertMember(
          'workshop-followups',
          state => state.data.email_address,
          state => state.data
        )
      );
triggers:
  webhook:
    id: trigger-webhook-id
    type: webhook
    enabled: true
edges:
  webhook->fetch-attendees-from-eventbrite:
    id: edge-wh-fetch
    source_trigger: webhook
    target_job: fetch-attendees-from-eventbrite
    condition_type: always
    enabled: true
  fetch-attendees-from-eventbrite->build-mailchimp-segment:
    id: edge-fetch-build
    source_job: fetch-attendees-from-eventbrite
    target_job: build-mailchimp-segment
    condition_type: on_job_success
    enabled: true
  build-mailchimp-segment->sync-segment-to-mailchimp:
    id: edge-build-sync
    source_job: build-mailchimp-segment
    target_job: sync-segment-to-mailchimp
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-long-history-same-step-0007

# history

## turn

### role

user

### content

I'm looking at the build-mailchimp-segment step. What does the .map(a => ({ ... })) bit actually produce?

## turn

### role

assistant

### content

It builds the array of member objects Mailchimp expects when adding people to a list — one entry per attendee, with `email_address`, a `status` of `subscribed`, and merge fields for first and last name. That array is then stashed onto `state.members` for the next step to consume.

## turn

### role

user

### content

OK. The attendees array comes from Eventbrite — does each attendee object have anything useful beyond email and name?

## turn

### role

assistant

### content

Yes. Eventbrite returns a lot per attendee: barcode, order date, ticket class, the `profile` object you're already reading from, and any custom survey questions answered at registration. We capture those into `attendee.answers` in the raw payload. If you want to use any of those, you'd map them out of `a.answers` or `a.profile` here.

## turn

### role

user

### content

We collect a marketing consent question on registration. It comes through as `a.profile.consent_marketing` (boolean). I don't want to email people who didn't tick it.

## turn

### role

assistant

### content

Got it. Then before building `members` you'd filter the attendees array down to only those with `consent_marketing` set to true. The cleanest place to do that is inside the same `fn` — add a filter step before the map.

## turn

### role

user

### content

And we'd want to tag the segment members so we can target follow-up campaigns per workshop. The workshop slug lives at state.workshop.slug.

## turn

### role

assistant

### content

Mailchimp lets you attach tags on the member object. You can include a `tags` array on each member entry — the workshop slug is a good per-workshop tag value, so every member of this batch gets tagged with it.

# turn

## role

user

## content

Right, let's apply both of those: only include attendees whose consent_marketing flag is true, and tag every member with the workshop slug. Update the code.
