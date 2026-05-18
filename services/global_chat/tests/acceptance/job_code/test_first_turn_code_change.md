---
id: global-chat.job-code.first-turn-code-change
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

First conversation turn on a job step page where the user explicitly asks for a code modification (add a timeout option to the HTTP get, and log when it fires). The router should route to job_code_agent (single-step edit on the focused page). The response should produce an updated job body for the focused step only — every other job in the YAML must be preserved unchanged. A `workflow_yaml` (and `job_code`) attachment with the modified job body is expected.

# quality_criteria

- The response produces updated job code for the fetch-from-mojaloop step that adds a timeout option to the HTTP get call (e.g. `timeout: 30000` or similar).
- The updated code adds a log message when the request times out / on the catch path.
- The change is applied only to the fetch-from-mojaloop body — the other two jobs (split-transactions-by-currency, post-to-finance-ledger) in the YAML are not modified.

# settings

## page

workflows/mojaloop-finance-ledger/fetch-from-mojaloop

## workflow_yaml

```yaml
name: mojaloop-finance-ledger
jobs:
  fetch-from-mojaloop:
    id: job-fetch-mojaloop-id
    name: Fetch Transactions from Mojaloop
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('/transactions', {
        query: { status: 'COMMITTED', updated_after: $.lastRunAt }
      });
      fn(state => {
        const txns = state.data.transactions || [];
        console.log(`Fetched ${txns.length} transactions from Mojaloop`);
        return { ...state, txns };
      });
  split-transactions-by-currency:
    id: job-split-id
    name: Split Transactions by Currency
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const byCurrency = state.txns.reduce((acc, t) => {
          (acc[t.currency] ||= []).push(t);
          return acc;
        }, {});
        return { ...state, byCurrency };
      });
  post-to-finance-ledger:
    id: job-post-ledger-id
    name: Post to Finance Ledger
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      each(
        Object.values($.byCurrency).flat(),
        post('/ledger/entries', state => ({
          reference: state.data.id,
          amount: state.data.amount,
          currency: state.data.currency,
          posted_at: state.data.committed_at
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "*/30 * * * *"
    enabled: true
edges:
  cron->fetch-from-mojaloop:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-from-mojaloop
    condition_type: always
    enabled: true
  fetch-from-mojaloop->split-transactions-by-currency:
    id: edge-fetch-split
    source_job: fetch-from-mojaloop
    target_job: split-transactions-by-currency
    condition_type: on_job_success
    enabled: true
  split-transactions-by-currency->post-to-finance-ledger:
    id: edge-split-post
    source_job: split-transactions-by-currency
    target_job: post-to-finance-ledger
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-first-turn-edit-0006

# turn

## role

user

## content

Mojaloop sometimes hangs and the run waits forever. Add a 30 second timeout to the get() request and log a clear message if it times out so I can spot it in the logs.
