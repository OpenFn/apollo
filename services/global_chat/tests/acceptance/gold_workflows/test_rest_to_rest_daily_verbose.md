---
id: global-chat.gold.rest-to-rest-verbose
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Verbose phrasing of the REST-to-REST baseline: the simplest end-to-end pattern
(cron-triggered fetch, transform, post) between two unauthenticated
JSONPlaceholder endpoints. Unlike the vague variant, the user spells out the
trigger cadence, the exact three-field target shape, the adaptor to use, and
explicitly asks to keep it simple.

What matters most given how the task is phrased:

- The spec is precise, so the output should honor it precisely: a once-a-day
  cron, the http adaptor as named, and a transform to exactly `userId` (the
  user's id), `title` (the user's name) and `body` (a string combining email
  and company name).
- Data-flow coherence across steps: the transform and the post step must agree
  on how transformed records pass between them. The downstream step consumes
  exactly what the upstream step produced, under the same state key, without
  re-fetching or rebuilding it.
- "Keep it simple: no branching or deduplication" is an explicit instruction,
  so added branching, dedup or auth logic counts against the response here.

The broader rubric this task comes from also covers idempotency, pagination,
validation and PII handling. The user explicitly ruled that kind of thing out,
so do not penalize its absence. We only want to catch clear issues: wrong
trigger, wrong adaptor, wrong field mapping, invented functions, or broken
data flow between steps.

The following workflow is a NON-BINDING reference showing one acceptable
shape. Do not require the candidate to match it: step count (fetch and
transform may be one step or two), job names, adaptor versions, the exact
`body` string format and the state key used between steps may all differ. Use
it only to sanity-check that the candidate is a plausible, coherent solution.

```yaml
name: daily-rest-to-rest-sync
jobs:
  Fetch-and-transform-users:
    name: Fetch and transform users
    adaptor: "@openfn/language-http@latest"
    body: |
      get('https://jsonplaceholder.typicode.com/users');

      fn((state) => {
        const records = (state.data || []).map((user) => ({
          userId: user.id,
          title: user.name,
          body: `${user.email} | ${user.company?.name ?? ''}`,
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
    cron_expression: 0 0 * * *
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

- The trigger is a cron scheduled once a day (e.g. `0 0 * * *` or similar), not a webhook or a different frequency.
- The http adaptor is used, as the user explicitly requested.
- A step fetches the user list from `https://jsonplaceholder.typicode.com/users` with an HTTP get.
- A transform maps each user to exactly the three requested fields: `userId` (the user's id), `title` (the user's name) and `body` (a string combining the user's email and company name).
- Each transformed record is POSTed to `https://jsonplaceholder.typicode.com/posts`.
- Job code uses http adaptor operations with plausible arguments rather than hand-rolled raw JavaScript, and each step returns state.
- Data-flow coherence: the posting step consumes the transform's output under the same state key it was written to, without re-fetching users or rebuilding the transformed objects.
- The solution stays simple as instructed: no branching, deduplication or auth logic beyond what was asked.

# turn

## role

user

## content

Build a scheduled workflow that copies records between two REST endpoints.
Trigger: cron, once a day.
Steps: GET the list of users from https://jsonplaceholder.typicode.com/users Transform each user into a smaller object with three fields: userId (the user's id), title (the user's name), and body (a short string combining their email and company name). POST each transformed record to https://jsonplaceholder.typicode.com/posts
Use the http adaptor. No authentication is required for this API. Keep it simple: no branching or deduplication.
