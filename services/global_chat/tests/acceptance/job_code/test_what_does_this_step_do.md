---
id: global-chat.job-code.what-does-this-step-do
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

User is on a specific step page in a 4-step workflow and asks the open-ended question "what does this step do?". Because the page URL identifies a single step, the router should route to job_code_agent and the answer should describe THAT step's code (the deduplication and dedup-key construction in the validate-and-dedupe-orders job) — not a tour of the whole workflow, and not a description of the next or previous step. No code change is expected.

# quality_criteria

- The response describes the validate-and-dedupe-orders step specifically, mentioning what it does to the orders array (dedupe by composite key, filter invalid ones).
- The response does NOT describe the whole workflow end-to-end as if the user asked about the entire pipeline.
- The response does NOT propose a code edit — the user asked an explanation question.

# settings

## page

workflows/shopify-to-netsuite-orders/validate-and-dedupe-orders

## workflow_yaml

```yaml
name: shopify-to-netsuite-orders
jobs:
  fetch-orders-from-shopify:
    id: job-fetch-shopify-id
    name: Fetch Orders from Shopify
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('https://example.myshopify.com/admin/api/2024-04/orders.json', {
        query: { status: 'any', updated_at_min: $.lastRunAt, limit: 250 }
      });
      fn(state => {
        const orders = state.data.orders || [];
        return { ...state, orders };
      });
  validate-and-dedupe-orders:
    id: job-validate-dedupe-id
    name: Validate and Deduplicate Orders
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const seen = new Set();
        const validOrders = [];
        const skipped = [];

        for (const order of state.orders) {
          const key = `${order.shop_id}::${order.order_number}`;
          if (!order.customer || !order.line_items?.length) {
            skipped.push({ key, reason: 'missing customer or line items' });
            continue;
          }
          if (seen.has(key)) {
            skipped.push({ key, reason: 'duplicate in batch' });
            continue;
          }
          seen.add(key);
          validOrders.push(order);
        }

        console.log(`Kept ${validOrders.length}, skipped ${skipped.length}`);
        return { ...state, orders: validOrders, skipped };
      });
  enrich-with-customer-record:
    id: job-enrich-id
    name: Enrich with Customer Record
    adaptor: "@openfn/language-postgresql@6.5.1"
    body: |
      each(
        $.orders,
        sql(state => ({
          query: 'SELECT id, netsuite_internal_id FROM customers WHERE shopify_id = $1',
          values: [state.data.customer.id]
        }))
      );
  upsert-orders-to-netsuite:
    id: job-upsert-netsuite-id
    name: Upsert Orders to NetSuite
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      each(
        $.orders,
        post('/services/rest/record/v1/salesOrder', state => ({
          entity: { internalId: state.data._netsuiteId },
          tranDate: state.data.created_at,
          item: state.data.line_items.map(li => ({
            item: { externalId: li.sku },
            quantity: li.quantity,
            amount: li.price
          }))
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "*/15 * * * *"
    enabled: true
edges:
  cron->fetch-orders-from-shopify:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-orders-from-shopify
    condition_type: always
    enabled: true
  fetch-orders-from-shopify->validate-and-dedupe-orders:
    id: edge-fetch-validate
    source_job: fetch-orders-from-shopify
    target_job: validate-and-dedupe-orders
    condition_type: on_job_success
    enabled: true
  validate-and-dedupe-orders->enrich-with-customer-record:
    id: edge-validate-enrich
    source_job: validate-and-dedupe-orders
    target_job: enrich-with-customer-record
    condition_type: on_job_success
    enabled: true
  enrich-with-customer-record->upsert-orders-to-netsuite:
    id: edge-enrich-upsert
    source_job: enrich-with-customer-record
    target_job: upsert-orders-to-netsuite
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-what-does-this-step-0005

# turn

## role

user

## content

What does this step do?
