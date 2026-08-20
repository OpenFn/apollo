---
id: global-chat.gold.rest-to-rest-vague
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Vague phrasing of the REST-to-REST baseline: the simplest end-to-end pattern
(cron-triggered fetch, transform, post) between two unauthenticated
JSONPlaceholder endpoints. The user names both endpoints and a daily cadence
but nothing else, so despite the loose wording the request is fully actionable
and a complete workflow should come back, not just clarifying questions.

What matters most given how the task is phrased:

- "Every morning" pins the trigger: a daily cron schedule, not a webhook.
- "Simplify each one" is deliberately underspecified. Any reasonable smaller
  projection of the user objects is acceptable; do not require particular
  field names.
- Both systems are plain REST, so the http adaptor with real functions (get,
  post, fn, each) is the expected shape, not invented helpers.

The broader rubric this task comes from also covers deduplication,
idempotency, pagination, validation and PII handling. None of those are asked
for here and the pattern does not need them, so do not penalize their absence.
We only want to catch clear issues: wrong trigger, wrong adaptor, invented
functions, broken data flow between steps, or invented complexity the user
never asked for.

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: step count (fetch and
transform may be one step or two), job names, adaptor versions, the chosen
"simplified" fields and the state key used between steps may all differ. Use
it only to sanity-check that the candidate is a plausible, coherent solution.

```yaml
name: daily-users-sync
jobs:
  Fetch-and-transform-users:
    name: Fetch and transform users
    adaptor: "@openfn/language-http@latest"
    body: |
      get('https://jsonplaceholder.typicode.com/users');

      fn((state) => {
        const records = (state.data || []).map((user) => ({
          userId: user.id,
          name: user.name,
          email: user.email,
        }));
        console.log(`Transformed ${records.length} users`);
        return { ...state, records };
      });
  Post-records:
    name: Post records to target
    adaptor: "@openfn/language-http@latest"
    body: |
      each(
        '$.records[*]',
        post('https://jsonplaceholder.typicode.com/posts', (state) => state.data)
      );
triggers:
  cron:
    type: cron
    enabled: true
    cron_expression: 0 6 * * *
edges:
  cron->Fetch-and-transform-users:
    condition_type: always
    enabled: true
    target_job: Fetch-and-transform-users
    source_trigger: cron
  Fetch-and-transform-users->Post-records:
    condition_type: on_job_success
    enabled: true
    target_job: Post-records
    source_job: Fetch-and-transform-users
```

# quality_criteria

- A complete workflow is produced (assumptions or placeholders are fine), rather than only clarifying questions, since the request names both endpoints and a schedule.
- The trigger is a daily cron (a morning schedule such as `0 6 * * *`, or any once-a-day expression), not a webhook.
- A step fetches the user list from `https://jsonplaceholder.typicode.com/users` with an HTTP get.
- Each user is reduced to some smaller object. Any sensible choice of fields is fine; do not require specific field names since the user only said "simplify".
- Each transformed record is POSTed to `https://jsonplaceholder.typicode.com/posts`.
- Job code uses http adaptor operations with plausible arguments rather than hand-rolled raw JavaScript, and each step returns state.
- The posting step consumes what the transform produced under a consistent state key, rather than re-fetching or rebuilding the data.
- No invented requirements: no authentication, deduplication or branching the user did not ask for.

# turn

## role

user

## content

Every morning, get the list of users from https://jsonplaceholder.typicode.com/users, simplify each one, and post them to https://jsonplaceholder.typicode.com/posts.
