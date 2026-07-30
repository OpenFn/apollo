---
id: global-chat.job-code.canvas-code-request
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The user is on the workflow canvas (a 2-segment page URL, no step open) but asks
for a code change to a named step. The router should resolve this to
job_code_agent for the fetch-orders step, so job_chat is told the user is viewing
the canvas while fetch-orders is the step it can edit — the case where the
on-screen view and the editable step deliberately differ.

Watch for two things. First, the edit must land on the fetch-orders step (not be
refused because "no step is open", and not bodged elsewhere). Second, the reply
must read like a normal answer: it must not surface internal mechanics (routing,
agents, subagents) or treat being on the canvas / not having a step open as a
limitation it narrates to the user.

# quality_criteria

- The fetch-orders step is updated to log a warning (e.g. a console.warn) when the API returns no orders — a guard that checks the fetched orders are empty.
- Only the fetch-orders step is changed; the other steps are left unchanged.
- The reply reads as a direct answer to the request and does NOT mention internal mechanics (routing, agents, subagents) or frame "being on the canvas" / "no step open" as a reason it cannot help.

# settings

## page

workflows/orders-sync

## workflow_yaml

```yaml
name: orders-sync
jobs:
  fetch-orders:
    id: job-fetch-orders-id
    name: Fetch Orders
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('/orders', { query: { since: $.lastRunAt } });
      fn(state => {
        const orders = state.data.orders || [];
        return { ...state, orders };
      });
  normalize-orders:
    id: job-normalize-orders-id
    name: Normalize Orders
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const orders = state.orders.map(o => ({
          id: o.id,
          total: Number(o.total_price),
          customerEmail: o.customer?.email,
          placedAt: o.created_at
        }));
        return { ...state, orders };
      });
  notify-fulfillment:
    id: job-notify-fulfillment-id
    name: Notify Fulfillment
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      each(
        $.orders,
        post('https://fulfillment.example.org/queue', state => ({
          body: state.data
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "*/30 * * * *"
    enabled: true
edges:
  cron->fetch-orders:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-orders
    condition_type: always
    enabled: true
  fetch-orders->normalize-orders:
    id: edge-fetch-normalize
    source_job: fetch-orders
    target_job: normalize-orders
    condition_type: on_job_success
    enabled: true
  normalize-orders->notify-fulfillment:
    id: edge-normalize-notify
    source_job: normalize-orders
    target_job: notify-fulfillment
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-canvas-code-request-0001

# turn

## role

user

## content

In the fetch-orders step, add a check that logs a warning if the API comes back with no orders.
