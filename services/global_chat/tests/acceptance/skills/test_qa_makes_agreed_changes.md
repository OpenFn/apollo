---
id: global-chat.skills.qa-makes-agreed-changes
service: global_chat
judges: [general]
---

# notes

The turn after the qa-whole-workflow test: /qa reported what should change and
offered to make it, and the user now agrees to some of it. The /qa
instructions are in the first turn of the history, as Apollo returned them.
The planner should make only the agreed changes, giving each step its listed
change rather than running the full review again, then check the steps fit.
Judge the outcome: which side of the key mismatch changes doesn't matter as
long as the two steps agree.

# quality_criteria

- After the changes, the upload step reads the patient list from the same key the fetch step writes it to.
- Both adaptors are pinned to `@openfn/language-http@7.0.0`.
- The existing comment in the fetch step is still there and unchanged.
- Nothing else in the code changes: no validation guards, URL changes or duplicate handling the user didn't agree to.
- The reply says briefly what was changed and reminds the user to test the workflow again, without repeating the full review.

# settings

## page

workflows/patient-sync

## workflow_yaml

```yaml
name: patient-sync
jobs:
  fetch-patients:
    id: job-fetch-patients-id
    name: Fetch patients
    adaptor: "@openfn/language-http@latest"
    body: |
      get('https://example.org/api/patients');
      // The API nests patients under results
      fn(state => ({ ...state, patients: state.data.results }));
  upload-patients:
    id: job-upload-patients-id
    name: Upload patients
    adaptor: "@openfn/language-http@latest"
    body: |
      each(
        $.patient_list,
        post('https://target.example.org/api/people', state => ({
          name: state.data.name,
          sex: state.data.gender,
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 2 * * *"
    enabled: true
edges:
  cron->fetch-patients:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-patients
    condition_type: always
    enabled: true
  fetch-patients->upload-patients:
    id: edge-fetch-upload
    source_job: fetch-patients
    target_job: upload-patients
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-skills-qa-makes-agreed-changes-0001

# history

## turn

### role

user

### content

[pg:workflow] <skill name="qa">
Review the workflow against what it's meant to do, taken from the user, a spec
or ticket they've shared, or the workflow itself. If you can't tell, ask. With
a spec, say which parts are met, partly met or missing, including edge cases
it implies but doesn't state.

Read first, then review every step, fixing what's wrong only if the user has
asked you to.

1. Read every step's code yourself with `inspect_job_code` and follow the data
   from the trigger to the last step, looking at what's below. Where steps
   don't fit, decide which side is right, so each step's fix can be settled
   before anything changes.

2. Have the job code agent review every step in parallel with the `qa-code`
   skill, which covers everything within a step. Your message carries what
   only you know: the contract each step keeps with its neighbours (what it
   reads and writes, under which names), which side of a mismatch it owns,
   that the other steps are being handled at the same time so it covers only
   its own, and what this conversation adds, such as what the spec asks of the
   step, limits the user has set, or that the user wants the changes made.
   Leave everything else in the step to the job code agent. Workflow changes,
   such as triggers, edges or adaptor versions, go through the workflow agent.

3. After making changes, read the changed steps again to confirm they now fit
   together.

How the steps fit together:
- the trigger is the right kind and enabled as intended;
- each step runs after everything it depends on;
- each step reads what the steps before it actually write, under the same
  names, in the same shape, and as plain JSON, since anything else is lost
  between steps;
- edges route data where it should go, so a failed or unmatched record can't
  fall through;
- no two steps do the same work;
- each step uses its system's own adaptor where one exists rather than plain
  HTTP;
- names other workflows rely on, such as collections, match exactly.

How it behaves live, over many runs. What fails quietly matters more than what
fails loudly, and these usually need the user's decision, so propose fixes
rather than prescribe them:
- a re-run that creates duplicates;
- a cursor or paging that skips records;
- a lookup that assumes exactly one match;
- adaptors on `@latest`, which can change under a live workflow and break it.
  The fix is to pin the version the workflow was tested on, which run logs
  often show; if you can't tell, say the pinned version is untested.

If dataclips are attached, check that the output means what the input meant.

Tell the user what you changed, if anything, then what should still change:
- Group it by whether it must, should or could change, worst first, naming the
  step and the operation. Anything that breaks, loses or exposes data, or
  breaks OpenFn's job-writing conventions, is a must.
- Offer cleanup as could-change in a line or two, and do it only if the user
  wants that kind of tidying.
- List a problem shared by several steps once.
- For a suggested change, show only the lines that change, with the
  recommended fix and any alternative in a line.
- Skip style nits a formatter would catch and speculative performance
  concerns.
- Say when a problem is inferred from the code rather than seen in the data.
- If nothing needs changing, say so. On a follow-up review, say which earlier
  issues are fixed and which aren't.

Then offer to make what should still change. When making changes, propose first any that would change behaviour beyond the
problem or need the user's decision, and for changes the user has agreed to,
give each step the ones listed for it rather than reviewing it again. If you
changed anything, remind the user to test the workflow again before relying
on it.
</skill>

Follow these instructions for the request below.

please review this before it goes live, and leave any comments alone

## turn

### role

assistant

### content

Here's my review of **patient-sync** before go-live. I haven't changed anything yet.

## Must change (breaks or loses data)

- **`upload-patients` reads the wrong key — this is the live failure.** The step iterates `$.patient_list`, but `fetch-patients` writes the array to `state.patients`. `each` calls `.length` on an undefined source, which is exactly the `Cannot read properties of undefined (reading 'length')` error in your log. Fix: iterate `state.patients`.

- **`fetch-patients` may be writing the array to the wrong path.** It sets `patients: state.data.results`, trusting the comment "API nests patients under results." That shape is unverified — if the real response isn't nested under `results`, `state.patients` is undefined and `upload-patients` fails even after the key fix. The 200 response in the log should be checked against the actual array path. (Inferred from code + log, not confirmed against the response body.)

## Should change (reliability)

- **Daily re-runs will create duplicate records** (both steps, cron runs nightly). `post` is non-idempotent, so every night re-POSTs every patient as a new person. This needs your decision — ideally an upsert/`put` keyed on a stable patient ID, or an existence check before posting. Biggest go-live risk after the two bugs above.

- **No validation in either step.** `fetch-patients` should guarantee an array to its consumer (fail loudly here rather than pushing `undefined` downstream); `upload-patients` posts patients with missing `name`/`gender` as-is. Also worth confirming the fetched objects actually use `name`/`gender`.

- **Adaptors pinned to `@latest`** (both steps). Your log shows the workflow was tested on `@openfn/language-http@7.0.0` — pinning to that avoids a live break when the adaptor changes.

## Could change (cleanup)

- **Hardcoded URLs** in both steps. Move the base URL into the credential (`baseUrl`) and pass just the path — keeps test/prod swappable.

Your existing comments will be left in place as you asked.

Want me to apply the fixes? I'd suggest doing the two **must** fixes plus pinning to `7.0.0` now. The duplicate-prevention approach needs a decision from you first — do you have a stable patient ID and does the target API support upsert? Once changes are made, test the workflow again before relying on it.

# turn

## role

user

## content

Yes, fix the key and pin both to 7.0.0. We don't have a stable patient ID yet, so leave the duplicates for now.
