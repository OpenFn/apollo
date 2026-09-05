---
id: job-chat.quality.lazy-state-debug
service: job_chat
runs: 3
judges: [general, openfn_code_quality]
---

# notes

Mechanism-knowledge probe. The user's code has the classic lazy-state bug: a
bare `state.data` passed as an operation argument, evaluated at load time
before the preceding get() has run, so the post sends an undefined body. The
run log shows the get succeeding and the post being rejected for a missing
body. The user's question is a plain debugging question with no hint at the
cause.

What this test watches for:

- Does the response identify the real mechanism (operation arguments are
  evaluated when the job loads, before any operation has run), rather than
  blaming the API, headers, async timing, or response parsing?
- Is the fix the idiomatic one — deferring the argument with a function
  (`state => state.data`) or `$.data`, keeping both requests as top-level
  operations? The classic wrong fixes are manually invoking the operation with
  state (`post(...)(state)`) or wrapping the post inside `fn()` and calling it
  by hand.

The issue is stochastic — grade what this run actually produced.

# quality_criteria

- The explanation identifies the actual cause: the bare `state.data` argument is evaluated when the job loads, before the get() has run, so the post body is undefined. It does not attribute the failure to the analytics API, authentication, headers, async timing, or the shape of the get response.
- The suggested fix defers the value — `post('/analytics/registrations', state => state.data)` or `$.data` (or an equivalent restructure that resolves the value at run time) — and keeps both requests as top-level operations.
- The response introduces no `)(state)` invocation and no new non-operation statements at the top level of the job.

# settings

## context.expression

```
// Pull yesterday's registrations
get('/registrations?since=-1d');

// Forward them to the analytics service
post('/analytics/registrations', state.data);
```

## context.adaptor

@openfn/language-http@6.5.4

## context.log

```
-- THIS IS A TEST RUN --
[CLI] ℹ Loaded env from .env
[R/T] ♦ Starting operation 1
[GET] 200 - /registrations?since=-1d (388ms)
[R/T] ♦ Operation 1 complete
[R/T] ♦ Starting operation 2
[POST] 400 - /analytics/registrations (102ms)
[R/T] ✘ Error in operation 2: Request failed with status code 400
[R/T] ✘ Server response: {"error":"request body must be a JSON object, got none"}
[R/T] ✘ Run failed
```

## suggest_code

true

## meta.session_id

sess-quality-lazy-state-debug-0001

# turn

## role

user

## content

The first request works fine - the run log shows the registrations coming back. But the analytics service rejects the second request saying the body is missing. The get clearly returns data, so why is the post sending nothing?
