"""Unit tests for the shared inspect_job_code tool executor and redaction."""

import time

import pytest
import yaml
from yaml_utils import (
    REDACTED_BODY,
    WITHHELD_NOTICE,
    find_job_in_yaml,
    get_page_view,
    get_step_name_from_page,
    has_unredacted_body,
    inspect_job_code,
    iter_body_holders,
    redact_job_bodies,
    remove_ids,
    stitch_job_code,
)

WORKFLOW_YAML = """\
name: wf
jobs:
  fetch-patients:
    name: Fetch Patients
    body: get('/patients');
  send-data:
    name: Send Data
    body: post('/data', $.data);
"""

WORKFLOW_YAML_WITH_IDS = """\
name: wf
jobs:
  fetch-patients:
    id: 5f2f36e7-3f42-4b0a-9c11-9b3f5a3d1a01
    name: Fetch Patients
    adaptor: "@openfn/language-http@latest"
    body: get('/patients');
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
"""


def test_redact_strips_bodies_and_ids_keeps_structure() -> None:
    redacted = redact_job_bodies(WORKFLOW_YAML_WITH_IDS)

    assert "get('/patients');" not in redacted
    assert "# [use inspect_job_code to view]" in redacted
    assert "id:" not in redacted
    # Structure the model needs stays intact
    assert "Fetch Patients" in redacted
    assert "@openfn/language-http@latest" in redacted
    assert "webhook->fetch-patients" in redacted
    assert "condition_type: always" in redacted


def test_inspect_returns_requested_bodies() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["fetch-patients", "send-data"])
    assert "get('/patients');" in result
    assert "post('/data', $.data);" in result


def test_inspect_matches_fuzzy_names() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["Fetch Patients"])
    assert "get('/patients');" in result


def test_inspect_reports_missing_job() -> None:
    result = inspect_job_code(WORKFLOW_YAML, ["nonexistent"])
    assert "No code found for job 'nonexistent'." in result


def test_inspect_handles_missing_yaml_and_keys() -> None:
    assert inspect_job_code(None, ["a"]) == "No workflow available to inspect."
    assert inspect_job_code(WORKFLOW_YAML, []) == "ERROR: No job keys provided."


# --- step lookup by name ----------------------------------------------------

NON_LATIN_WORKFLOW_YAML = """\
name: wf
jobs:
  patient-check:
    name: 患者確認
    body: get('/patients');
  send-data:
    name: データ送信
    body: post('/data', $.data);
  verify:
    name: Проверка данных
    body: check();
"""


def test_find_job_matches_the_right_non_latin_name() -> None:
    key, job = find_job_in_yaml(NON_LATIN_WORKFLOW_YAML, "データ送信")
    assert key == "send-data"
    assert job["name"] == "データ送信"


def test_find_job_does_not_cross_match_non_latin_names() -> None:
    """Every non-Latin name used to normalize to "", so any non-Latin lookup
    matched the first non-Latin job in the workflow."""
    key, job = find_job_in_yaml(NON_LATIN_WORKFLOW_YAML, "Проверка")
    assert key is None
    assert job is None

    key, _ = find_job_in_yaml(NON_LATIN_WORKFLOW_YAML, "Проверка данных")
    assert key == "verify"


def test_find_job_lookup_is_still_fuzzy_for_latin_names() -> None:
    assert find_job_in_yaml(WORKFLOW_YAML, "Fetch Patients")[0] == "fetch-patients"
    assert find_job_in_yaml(WORKFLOW_YAML, "FETCH-PATIENTS")[0] == "fetch-patients"


def test_find_job_ignores_a_lookup_key_with_nothing_to_match_on() -> None:
    assert find_job_in_yaml(NON_LATIN_WORKFLOW_YAML, "!!!") == (None, None)
    assert find_job_in_yaml(NON_LATIN_WORKFLOW_YAML, "") == (None, None)


def test_find_job_matches_a_decomposed_name() -> None:
    yaml_str = "jobs:\n  verify:\n    name: V\u00e9rifier\n"
    assert find_job_in_yaml(yaml_str, "Ve\u0301rifier")[0] == "verify"


# --- page breadcrumb parsing ------------------------------------------------


def test_page_view_classifies_the_three_shapes() -> None:
    assert get_page_view("workflows/wf") == ("overview", None)
    assert get_page_view("workflows/wf/settings") == (None, None)
    assert get_page_view("workflows/wf/fetch-patients") == ("step", "fetch-patients")
    assert get_page_view("projects/p") == (None, None)
    assert get_page_view(None) == (None, None)
    assert get_page_view("workflows") == (None, None)


def test_page_view_keeps_a_slash_inside_a_step_name() -> None:
    """A step name containing "/" used to silently lose the step focus."""
    assert get_page_view("workflows/wf/Import A/B") == ("step", "Import A/B")
    assert get_step_name_from_page("workflows/wf/Import A/B") == "Import A/B"


def test_page_view_keeps_a_non_latin_step_name() -> None:
    assert get_step_name_from_page("workflows/wf/患者確認") == "患者確認"


# --- redaction must never fall back to the unredacted document ----------------

WORKFLOW_WITH_NULL_JOB = """\
name: wf
jobs:
  fetch:
    name: Fetch
    body: |
      const SECRET = 'do-not-send-me';
      get('/patients');
  half-written:
"""


def test_redaction_survives_a_null_job_entry() -> None:
    """A bare `half-written:` entry used to raise, and the handler returned the
    original string — sending every real job body to the planner and job_chat,
    where a placeholder was intended."""
    redacted = redact_job_bodies(WORKFLOW_WITH_NULL_JOB)

    assert "do-not-send-me" not in redacted
    assert "get('/patients')" not in redacted
    assert "# [use inspect_job_code to view]" in redacted


def test_redaction_withholds_rather_than_leaking_when_it_cannot_parse() -> None:
    """Returning the input on failure is the one thing this function must not do."""
    unparseable = "jobs:\n  a:\n   body: |\n  \tbad indent\n     x: [\n"

    result = redact_job_bodies(unparseable)

    assert "bad indent" not in result


def test_redaction_leaves_a_bodyless_document_intact() -> None:
    """Nothing to redact, so the structure must survive unchanged."""
    redacted = redact_job_bodies("name: wf\njobs:\n  a:\n    name: A\n")

    assert yaml.safe_load(redacted) == {"name": "wf", "jobs": {"a": {"name": "A"}}}


LIGHTNING_PROJECT = """\
name: my-project
workflows:
  my-workflow:
    jobs:
      a:
        name: A
        body: |
          const SECRET = 'leak-me';
"""


def test_a_lightning_project_export_is_redacted_not_returned_verbatim() -> None:
    """The shape with no top-level `jobs:`.

    The old guard returned the input for any document it did not recognise,
    behind a condition that was always true on that branch, so this came back
    with every body in it.
    """
    redacted = redact_job_bodies(LIGHTNING_PROJECT)

    assert "leak-me" not in redacted
    assert "# [use inspect_job_code to view]" in redacted


@pytest.mark.parametrize(
    "document",
    [
        "steps:\n  - body: SECRET_X\n",
        "a:\n  b:\n    c:\n      body: SECRET_X\n",
        "- body: SECRET_X\n",
        "wrapper:\n  jobs:\n    a:\n      body: SECRET_X\n",
    ],
)
def test_no_document_shape_returns_a_body_verbatim(document: str) -> None:
    assert "SECRET_X" not in redact_job_bodies(document)


def test_withholding_tells_the_model_what_happened() -> None:
    """An empty structure reads as "this workflow has no steps", which is a
    worse lie than "I cannot show you this"."""
    withheld = redact_job_bodies("x: [")

    assert "withheld" in withheld
    assert "Do not conclude that it is empty" in withheld


def test_stitching_a_missing_job_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    """It returns the original either way; the planner logs success regardless,
    so silence here meant the generated code vanished without trace."""
    with caplog.at_level("ERROR"):
        stitch_job_code(WORKFLOW_YAML, "no-such-job", "get('/x');")

    assert any("discarded" in record.message for record in caplog.records)


def test_stitch_tolerates_a_null_job_entry() -> None:
    stitched = stitch_job_code(WORKFLOW_WITH_NULL_JOB, "fetch", "post('/x');")

    assert "post('/x');" in stitched
    assert stitch_job_code(WORKFLOW_WITH_NULL_JOB, "half-written", "x();") is not None


# --- one walker, every shape ---------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        "jobs:\n  a:\n    body: {k: SECRET_X}\n",
        "jobs:\n  a:\n    body: [SECRET_X]\n",
        "jobs:\n  a:\n    body: !!binary U0VDUkVUX1g=\n",
        "!!omap\n- a:\n    body: SECRET_X\n",
        "jobs:\n  a: &x\n    body: SECRET_X\n  b: *x\n",
        "wrapper:\n  - nested:\n      jobs:\n        a:\n          body: SECRET_X\n",
    ],
)
def test_a_body_of_any_type_in_any_container_is_redacted(document: str) -> None:
    """`isinstance(body, str)` gated both the redactor and the check meant to
    catch what the redactor skipped, so the backstop could not catch anything
    the redactor missed."""
    redacted = redact_job_bodies(document)

    assert "SECRET_X" not in redacted
    assert "U0VDUkVU" not in redacted


def test_a_numeric_body_is_redacted() -> None:
    assert "12345" not in redact_job_bodies("jobs:\n  a:\n    body: 12345\n")


def test_the_walker_terminates_on_a_self_referential_anchor() -> None:
    redacted = redact_job_bodies("a: &x\n  self: *x\n  body: SECRET_X\n")

    assert "SECRET_X" not in redacted


def test_has_unredacted_body_agrees_with_the_walker() -> None:
    """The backstop must use a different predicate from the redactor, or it is
    structurally incapable of catching what the redactor skipped."""
    for document in ("jobs:\n  a:\n    body: [SECRET_X]\n", "x:\n  - body: 5\n"):
        data = yaml.safe_load(document)
        assert has_unredacted_body(data)
        for holder in iter_body_holders(data):
            holder["body"] = REDACTED_BODY
        assert not has_unredacted_body(data)


def test_a_comment_only_document_is_not_returned_verbatim() -> None:
    """Every `return yaml_str` is a leak waiting for a shape that skips the
    redaction above it."""
    assert redact_job_bodies("# just a comment\n") == ""


# --- a document that is not a mapping is not a shape we walked -----------------


@pytest.mark.parametrize(
    "document",
    [
        "SECRET_X\n",
        "- SECRET_X\n- more\n",
        "12345\n",
        "- - SECRET_X\n",
        "'SECRET_X'\n",
    ],
)
def test_a_non_mapping_document_is_withheld(document: str) -> None:
    """`workflow_yaml` is an unvalidated client string. A top-level scalar or a
    sequence of strings has no `body` key for the walker to find, so it used to
    sail through untouched and come back whole."""
    result = redact_job_bodies(document)

    assert "SECRET_X" not in result
    assert "12345" not in result
    assert result == WITHHELD_NOTICE




# --- the id walker needs the same cycle guard as the body walker ---------------


#: Comfortably above the alias bomb's real size, so the assertion below says
#: "this document is tiny" without pinning an exact byte count.
SMALL_DOCUMENT_BYTES = 600


def _alias_bomb(levels: int = 8, width: int = 9) -> str:
    """A small document that expands enormously through YAML aliases."""
    lines = ["a0: &a0 {id: x, body: SECRET_X}"]
    for level in range(1, levels + 1):
        refs = ",".join([f"*a{level - 1}"] * width)
        lines.append(f"a{level}: &a{level} [{refs}]")
    return "\n".join(lines) + "\n"


def test_the_id_walker_terminates_on_alias_expansion() -> None:
    """`iter_body_holders` got the visited set and `remove_ids` did not. Eight
    levels of nine-way expansion is 400 bytes on the wire and about seven
    seconds of walking without it, and `workflow_yaml` is client-supplied."""
    document = _alias_bomb()
    assert len(document) < SMALL_DOCUMENT_BYTES

    data = yaml.safe_load(document)
    start = time.monotonic()
    remove_ids(data)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"remove_ids took {elapsed:.1f}s on a {len(document)}-byte document"
    assert "id" not in data["a0"]


def test_redaction_terminates_on_alias_expansion() -> None:
    document = _alias_bomb()

    start = time.monotonic()
    redacted = redact_job_bodies(document)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
    assert "SECRET_X" not in redacted


def test_remove_ids_still_walks_tuples() -> None:
    data = {"jobs": [("a", {"id": "keep-me-out", "name": "A"})]}

    remove_ids(data)

    assert "id" not in data["jobs"][0][1]


# --- the fuzzy lookup writes, so it must not guess -----------------------------

AMBIGUOUS_WORKFLOW = """\
name: wf
jobs:
  upload-data:
    name: Legacy uploader
    body: legacy();
  upload-data-2:
    name: Upload Data
    body: current();
"""


def test_an_exact_name_beats_an_earlier_key_fold() -> None:
    """The result goes to `stitch_job_code`, which replaces that step's body.
    Taking the first fold hit let `upload-data`'s key fold beat
    `upload-data-2`'s exact name, so the model's code overwrote the legacy
    step."""
    assert find_job_in_yaml(AMBIGUOUS_WORKFLOW, "Upload Data")[0] == "upload-data-2"


def test_an_exact_key_still_wins_outright() -> None:
    assert find_job_in_yaml(AMBIGUOUS_WORKFLOW, "upload-data")[0] == "upload-data"


def test_an_ambiguous_fold_is_refused_rather_than_guessed() -> None:
    workflow = "jobs:\n  a:\n    name: Fetch Data\n  b:\n    name: fetch-data\n"

    assert find_job_in_yaml(workflow, "FETCH DATA") == (None, None)


def test_an_unambiguous_fold_still_resolves() -> None:
    assert find_job_in_yaml(AMBIGUOUS_WORKFLOW, "upload data 2")[0] == "upload-data-2"
