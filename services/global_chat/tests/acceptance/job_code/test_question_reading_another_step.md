---
id: global-chat.job-code.question-reading-another-step
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The user is on the last step (notify-fulfillment) and asks what fields each order
has "at this point". The focused step only consumes `$.orders`; the shape those
orders actually have is defined by the UPSTREAM normalize-orders step, not by any
code visible in the focused step. To answer correctly the assistant has to read
the normalize-orders step and describe the fields it produces.

This exercises the read-only path new to job_chat in subagent mode: it should
route to job_code_agent, use inspect_job_code to read the upstream step, and
answer — without escalating to the planner and without a code change. (The
planner could also field it; either way the answer must reflect the normalize
step's real output, not a generic guess.) The key failure mode to catch is the
model answering from thin air, or replying that it cannot see the data / the
other step.

# quality_criteria

- The response describes the normalized order shape produced upstream by the normalize-orders step: an id, a numeric total, a customerEmail, and a placedAt (timestamp).
- The answer is grounded in the actual upstream code, not a generic description of "an order", and it does NOT claim it cannot see the data or the other step.
- The response does NOT propose or apply a code change — the user asked a question.

# settings

## page

workflows/orders-sync/notify-fulfillment

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

sess-job-code-question-reading-another-step-0001

# turn

## role

user

## content

Before I post these to fulfillment, what fields does each order actually have at this point?
