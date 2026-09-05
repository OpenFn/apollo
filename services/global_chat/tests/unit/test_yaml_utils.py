"""Unit tests for the shared inspect_job_code tool executor and redaction."""

from yaml_utils import (
    find_job_in_yaml,
    get_page_view,
    get_step_name_from_page,
    inspect_job_code,
    redact_job_bodies,
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
