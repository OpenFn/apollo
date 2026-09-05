---
id: job-chat.quality.patient-dedup-codegen
service: job_chat
runs: 3
judges: [general, openfn_code_quality]
---

# notes

Elicitation test for recurring code-quality habits. The task is a realistic
first-code request for a webhook-fed OpenMRS dedup step, worded the way a real
user would put it — nothing in the message hints at the rules under test. The
task shape deliberately embeds three temptations:

1. "put a placeholder there and I'll swap it in" tempts a top-level
   `const IDENTIFIER_TYPE_UUID = '...'` outside any operation (top-level
   statement anti-pattern).
2. The lookup by a value from the webhook payload tempts a bare `state.x`
   inside an operation's arguments (lazy-state bug: arguments are evaluated at
   load time), including via template literals or nested query objects. A
   related wrong turn is manually invoking an operation with state (`)(state)`).
3. The final trace log after the create tempts reading the submission id from
   `state.data` after the write, when `state.data` already holds the OpenMRS
   response.

The issue is stochastic — grade what this run actually produced against the
criteria. Judge the code however it is delivered (code_edits or inline).

Grading notes: `$` is a compiled lazy reference and is valid nested inside
object arguments (e.g. `get('patient', { q: $.data.national_id })`) — do not
flag nested `$` as a lazy-state bug; only bare `state.x` outside a function is.
`fnIf` is a documented language-common helper — do not flag it as hallucinated.

# quality_criteria

- Every value read from state inside an operation's arguments is deferred with a function (`state => ...`) or the `$` shorthand. No bare `state.x` is evaluated directly in an operation call's arguments — including inside template literals in the first argument or nested inside plain option/query objects. (`$` counts as deferred even when nested inside an object argument.)
- The top level of the job contains only operation calls. The identifier-type placeholder value and any helpers or conditionals live inside `fn()` or the callback that uses them — not as top-level `const`/`let`/`var` or free-standing statements.
- No operation is manually invoked with state: the `)(state)` pattern does not appear anywhere.
- The final log gets the submission id from the webhook payload as preserved by the job itself (e.g. copied to a state key before the write, or read from the input before any operation overwrote `state.data`) — not from `state.data` after the lookup/create response has replaced it. The patient uuid comes from the operation's response.
- The code is a plausible, complete implementation of the request: look up by national ID, create only when no match exists (with the national ID identifier and a placeholder identifier-type UUID), and log the trace line. Callbacks that continue the pipeline return state.

# settings

## context.expression

```
// Add operations here
```

## context.adaptor

@openfn/language-openmrs@latest

## context.input

```
{
  "_id": "kobo-8842",
  "given_name": "Amina",
  "family_name": "Yusuf",
  "sex": "F",
  "date_of_birth": "1993-04-12",
  "national_id": "NID-55821-77"
}
```

## suggest_code

true

## meta.session_id

sess-quality-patient-dedup-0001

# turn

## role

user

## content

This step receives a form submission from our webhook - there's a sample in the input tab. Look the patient up in OpenMRS by the national ID from the form, and if they don't exist yet, create them with the name, sex and birthdate. New patients should get the national ID saved as an identifier - the identifier type UUID is configured on our instance so just put a placeholder and I'll swap it in. At the end log the submission id and the patient's uuid (found or created) on one line so I can trace runs.
