"""Integration test for the planner's attachment forwarding decision.

The unit and service tiers already prove the plumbing: a named attachment
reaches the subagent, an unnamed one does not. What they cannot prove is
whether a real planner names the right ones.

This hits the live Anthropic API (manual/nightly, costs tokens). Both scenarios
ask for two unrelated things at once so the router escalates to the planner.
They differ in what the log is worth to the subagent:

- a single mistake the planner can read off the log and restate in a sentence,
  where forwarding the log would be waste; and
- a long list of per-field errors that no message can restate faithfully, where
  the subagent has to read the log itself.

Passing means the planner told the two apart. This is a judgement call by a
model, so treat a failure as a prompt regression to investigate rather than a
broken build.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from global_chat.global_chat import main as global_chat_main  # noqa: E402

pytestmark = pytest.mark.integration

WORKFLOW_YAML = """\
name: patient-sync
jobs:
  fetch-patients:
    id: 5f2f36e7-3f42-4b0a-9c11-9b3f5a3d1a01
    name: Fetch Patients
    adaptor: "@openfn/language-http@latest"
    body: |
      get('/patients');
      fn(state => ({ ...state, records: state.data.results }));
  post-to-openmrs:
    id: 8a1c22d0-6e4f-49d3-b6a2-4bfeb1f0c902
    name: Post to OpenMRS
    adaptor: "@openfn/language-openmrs@latest"
    body: |
      each(
        $.patients,
        create('patient', state => state.data)
      );
triggers:
  webhook:
    id: 2d7f80b3-1c55-47a9-8e2f-6a90d24c7a03
    type: webhook
edges:
  webhook->fetch-patients:
    id: c4e9a1f6-0d82-4c37-9b54-7e315f68bd04
    source_trigger: webhook
    target_job: fetch-patients
    condition_type: always
  fetch-patients->post-to-openmrs:
    id: 7b3e1d95-2a68-4f11-b0c3-8d51e2a94f06
    source_job: fetch-patients
    target_job: post-to-openmrs
    condition_type: on_job_success
"""

# The cause is only visible in the log: the fetch step writes state.records,
# the post step reads $.patients. Nothing in the YAML says so.
RUN_LOG = """\
[R/T] Starting job fetch-patients
[JOB] GET /patients -> 200 OK, 143 results
[R/T] Job fetch-patients succeeded in 1.882s
[R/T] Starting job post-to-openmrs
[JOB] each() resolved $.patients to undefined
[JOB] ✗ TypeError: Cannot read properties of undefined (reading 'length')
[JOB]     at each (@openfn/language-common/dist/index.js:212)
[R/T] Job post-to-openmrs failed: TypeError
[R/T] Run finished with errors
"""


FAILING_STEP = "post-to-openmrs"


def tool_calls_for(response: dict, tool_name: str) -> list[dict]:
    return [
        call.get("input", {})
        for call in response.get("meta", {}).get("tool_calls", [])
        if call.get("tool") == tool_name
    ]


# A per-field rejection list. The planner cannot restate twenty of these in a
# tool message without losing detail, so the subagent needs the log itself.
FIELD_ERROR_LOG = "[R/T] Starting job post-to-openmrs\n" + "\n".join(
    f"[JOB] ✗ 400 Bad Request (patient {i}): field '{field}' {problem}"
    for i, (field, problem) in enumerate(
        [
            ("birthdate", "must be yyyy-MM-dd, got '12/04/1987'"),
            ("gender", "must be one of M, F, O; got 'male'"),
            ("names[0].givenName", "is required"),
            ("identifiers[0].identifierType", "unknown uuid"),
            ("addresses[0].country", "must be an ISO 3166 code, got 'Kenya'"),
            ("telecom.phone", "must be E.164, got '0722 000 111'"),
            ("deathDate", "must not be set when dead is false"),
            ("attributes[2].value", "exceeds 50 characters"),
        ] * 3,
        start=1,
    )
) + "\n[R/T] Job post-to-openmrs failed: 24 records rejected"


def run(content: str, log: str) -> dict:
    return global_chat_main({
        "content": content,
        "workflow_yaml": WORKFLOW_YAML,
        "page": "workflows/patient-sync/post-to-openmrs",
        "history": [],
        "attachments": [{"type": "log", "content": log}],
    })


def report(label: str, response: dict) -> list[dict]:
    """Print what the planner actually chose, so a failure is readable."""
    job_calls = tool_calls_for(response, "call_job_code_agent")
    print(f"\n[{label}] agents: {response['meta']['agents']}")
    for call in job_calls:
        print(f"  attachments={call.get('attachments')!r}  message={call.get('message', '')[:110]}")
    return job_calls


@pytest.fixture(scope="module")
def diagnosed_by_planner() -> dict:
    """One clear mistake: the planner can read it off the log and say what to fix."""
    return run(
        "Two things: add a step at the end that posts a summary to Slack, and work out "
        "why the OpenMRS step failed in last night's run. I've attached the log.",
        RUN_LOG,
    )


@pytest.fixture(scope="module")
def needs_the_subagent_to_read() -> dict:
    """Two dozen per-field rejections: no message can carry them faithfully."""
    return run(
        "Add a Slack step at the end, and fix this step so the records stop getting "
        "rejected — the log has every rejection from last night's run.",
        FIELD_ERROR_LOG,
    )


def log_for(job_calls: list[dict], job_key: str) -> list[str]:
    """What a call targeting `job_key` asked for, or [] if there was no such call."""
    for call in job_calls:
        if call.get("job_key") == job_key:
            return call.get("attachments") or []
    return []


def unrelated_calls(job_calls: list[dict]) -> list[dict]:
    return [c for c in job_calls if c.get("job_key") != FAILING_STEP]


def test_two_asks_in_one_message_reach_the_planner(diagnosed_by_planner: dict) -> None:
    assert "planner" in diagnosed_by_planner["meta"]["agents"]


@pytest.mark.parametrize("scenario", ["diagnosed_by_planner", "needs_the_subagent_to_read"])
def test_the_unrelated_new_step_is_never_given_the_log(request: pytest.FixtureRequest, scenario: str) -> None:
    """The point of letting the planner choose, and the stable half of it.

    Writing a Slack step has nothing to do with last night's OpenMRS failure, so
    that call must not be billed for the log. This holds in both scenarios; what
    the planner does for the *failing* step is a closer call (see below).
    """
    job_calls = report(scenario, request.getfixturevalue(scenario))
    assert job_calls, "the planner never called the job code agent"

    for call in unrelated_calls(job_calls):
        assert "log" not in (call.get("attachments") or []), (
            f"the log went to '{call.get('job_key')}', which the request never mentioned"
        )


def test_detail_the_planner_cannot_restate_is_forwarded(needs_the_subagent_to_read: dict) -> None:
    """Twenty-four per-field rejections have to be read, not summarised.

    Only asserted for this scenario. With a single one-line cause the planner may
    reasonably either hand the log over or just say what to change — observed
    runs have done both — so asserting either way there would only be flaky.
    """
    job_calls = report("field errors", needs_the_subagent_to_read)
    assert "log" in log_for(job_calls, FAILING_STEP), (
        "the planner summarised a per-field rejection list instead of handing it over: "
        f"{[(c.get('job_key'), c.get('attachments')) for c in job_calls]}"
    )


def test_the_answer_still_names_the_state_key_mismatch(diagnosed_by_planner: dict) -> None:
    """Whatever it forwards, the user still gets the diagnosis."""
    text = diagnosed_by_planner["response"].lower()
    assert "records" in text
    assert "patients" in text
