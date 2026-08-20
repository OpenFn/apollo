---
id: job-chat.tmp.repro-gmail-sendmessage-keys
service: job_chat
runs: 5
judges: [general, openfn_code_quality]
---

# notes

Reproduction of a user report: when asked to send mail with the gmail adaptor,
job_chat writes `sendMessage({ to, subject, text: ... })` or
`sendMessage({ to, subject, message: ... })`. Neither key exists on
`SendMessageOptions` — the body key is `body` — so the operation sends an empty
message or throws at run time. The reporter saw it "at least half a dozen
times", hence `runs: 5`: this measures a rate, not a single verdict.

Why it happens (not a judgement call — verified in the code):

- `job_chat/prompt.py:generate_system_message` injects ONLY the `signature`
  column from `adaptor_function_docs`. For gmail@3.2.0 the entire adaptor
  context the model receives is a bare name list, ending in
  `sendMessage(message)`. The stored `function_data` JSONB does hold the
  param descriptions and the docsite example (which uses `body`), but nothing
  reads them.
- `load_adaptor_docs.filter_function_docs` keeps only doclets of kind
  `function` / `external-function` / `external`, so the `SendMessageOptions`
  typedef — the only place the `body`/`to`/`subject`/`attachments` property
  names are defined — is never stored at all.
- `job_chat/retrieve_docs.py:search_docs` pins the docsite RAG to
  `docs_type="general_docs"`, so the adaptor docs page can't fill the gap
  either. The prompt even says so: "not adaptor-specific APIs, which are
  included separately."

So `body` appears nowhere in the prompt, and the model falls back on its
nodemailer / SendGrid priors, where the body key IS `text` (or `html`, or
`message`). The user's complaint that it ignores "the adaptor doc" is
accurate about docs.openfn.org, but that document never reaches the model.

Note for local runs: gmail docs must be present in `adaptor_function_docs`, or
the adaptor block degrades to "The user is using an OpenFn Adaptor to write the
job." and the test is no longer a faithful repro. Confirm with
`select signature from adaptor_function_docs where adaptor_name = '@openfn/language-gmail'`.

Expected behaviour once fixed: the message object uses `body`, and no invented
key. A model that cannot know the key names should say so or ask, not guess
silently.

# quality_criteria

- Any `sendMessage` call passes the body text under the key `body`.
- The message object uses no invented key for the body — specifically NOT `text`, `message`, `html`, `content`, or `bodyText`.
- Recipient and subject use the documented keys `to` and `subject`.
- The code calls only functions that exist in the gmail adaptor (`sendMessage`, `getContentsFromMessages`, `getMessageById`) or in language-common; it does not invent a mail-sending function such as `send`, `sendEmail`, or `sendMail`.
- The response does not claim the adaptor supports message fields it has not been shown; if it is unsure of the option names it says so or asks, rather than presenting a guessed key as documented.

# settings

## context.expression

```js
fn(state => {
  const failed = state.data.filter(r => r.status === 'error');
  return { ...state, failed };
});
```

## context.adaptor

@openfn/language-gmail@3.2.0

## context.input

```json
{
  "data": [
    { "id": "r-1001", "patient": "P-88", "status": "ok" },
    { "id": "r-1002", "patient": "P-91", "status": "error", "reason": "missing dob" },
    { "id": "r-1003", "patient": "P-92", "status": "error", "reason": "bad org unit" }
  ]
}
```

## suggest_code

true

## meta.session_id

sess-tmp-repro-gmail-sendmessage-keys-0001

# turn

## role

user

## content

now email the failed records to data-team@example.org as a summary, subject "Nightly sync failures"
