---
id: global-chat.rest-to-rest-sync-with-cron
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

From-scratch scheduled REST-to-REST sync with fully specified job code. No existing YAML, no history. The user gives a precise spec: a daily cron trigger, an HTTP GET of a user list, a transform into a three-field shape (userId, title, body), and an HTTP POST of each transformed record. The planner should be invoked, call the workflow agent to produce the structure with a cron trigger, then call the job code agent to fill in the bodies.

The key thing this test probes is data-flow coherence across steps: the transform step and the post step must agree on how the transformed records are passed between them. The steps should not read as if written in isolation — the downstream step must consume exactly what the upstream step produced, under the same name, without re-fetching or rebuilding it.

The following workflow is a NON-BINDING reference showing one acceptable shape. Do not require the candidate to match it (adaptor versions, job names, whether GET and transform are one step or two, and the exact state key may all differ). Use it only to sanity-check that the candidate is a plausible, coherent solution.

```yaml
name: " Daily REST Endpoint Sync (Manual)"
jobs:
  Fetch-and-transform-users:
    name: Fetch and transform users
    adaptor: "@openfn/language-http@latest"
    body: >-


      get('https://jsonplaceholder.typicode.com/users');


      fn((state) => {
        const users = state.data || [];
        const records = users.map((user) => ({
          userId: user.id,
          title: user.name,
          body: `Email: ${user.email} | Company: ${user.company?.name ?? 'N/A'}`,
        }));
        console.log(`Transformed ${records.length} users`);
        return { ...state, records };
      });
  Post-records-to-target:
    name: Post records to target
    adaptor: "@openfn/language-http@7.3.2"
    body: >
      each(
        '$.records[*]',
        post('https://jsonplaceholder.typicode.com/posts', (state) => state.data)
      );


      fn((state) => {
        console.log(`Posted ${state.records?.length ?? 0} records`);
        return state;
      });
triggers:
  cron:
    type: cron
    enabled: false
    cron_expression: 0 0 * * *
    cron_cursor_job: null
edges:
  cron->Fetch-and-transform-users:
    condition_type: always
    enabled: true
    target_job: Fetch-and-transform-users
    source_trigger: cron
  Fetch-and-transform-users->Post-records-to-target:
    condition_type: on_job_success
    enabled: true
    target_job: Post-records-to-target
    source_job: Fetch-and-transform-users
```

# quality_criteria

- The workflow uses a cron trigger scheduled to run once a day (e.g. a `0 0 * * *` daily expression), not a webhook or a different frequency.
- A step fetches the user list from the source endpoint (`https://jsonplaceholder.typicode.com/users`) using an HTTP get.
- A transform maps each user into an object with exactly the three requested fields: `userId` (the user's id), `title` (the user's name), and `body` (a string combining the user's email and company name).
- A step POSTs each transformed record to the target endpoint (`https://jsonplaceholder.typicode.com/posts`) using an HTTP post.
- Data-flow coherence: the posting step consumes the exact data the transform step produced, referencing it under the same state key/name that the transform step wrote to. There is no key mismatch between the producing and consuming steps.
- The posting step does not re-fetch the users or rebuild the transformed objects itself — it consumes the upstream output as-is rather than duplicating the transform.
- The solution stays simple as requested: no branching, filtering, deduplication, or auth logic beyond what the user asked for.

# turn

## role

user

## content

Build a scheduled workflow that copies records between two REST endpoints.
Trigger: cron, once a day.
Steps: GET the list of users from https://jsonplaceholder.typicode.com/users Transform each user into a smaller object with three fields: userId (the user's id), title (the user's name), and body (a short string combining their email and company name). POST each transformed record to https://jsonplaceholder.typicode.com/posts

No authentication is required for this API. Keep it simple: no branching or deduplication.
