---
id: webhook-response-config
order: 30
---

### Optional webhook response configuration

A webhook trigger may include optional sub-keys that control its HTTP response: `webhook_reply` and `webhook_response_config`.

The values of can `webhook_reply` can be:
- `before_start` (async, default): responds immediately with the work order/run ID.
- `after_completion` (sync): waits for the workflow to finish, responds with final state.

 The value `webhook_response_config` is an object with two optional keys: `error_code` and `success_code`. This determines the HTTP response code for a workflow based on the exit state.

If these sub-keys are present, preserve them EXACTLY. Don't add them proactively. Only edit them if the user asks. Warn before switching away from `custom`/`after_completion` that any custom response config will be lost.
