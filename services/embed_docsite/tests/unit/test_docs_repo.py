"""Unit tests for the git-backed docs checkout.

`_run_git` is replaced with a fake that records argv
and never spawns `git`.
"""
import subprocess

import embed_docsite.docs_repo as m
import pytest
from util import ApolloError

FAKE_SHA = "deadbeefcafefeed0000111122223333deadbee"

HTTP_BAD_REQUEST = 400
HTTP_MISCONFIGURED = 500
HTTP_UPSTREAM_ERROR = 503


class FakeCompletedProcess:
    def __init__(self, stdout=""):
        self.stdout = stdout


def make_git(rev_sha=FAKE_SHA, fail_on=None):
    """A fake `_run_git`. `fail_on(args) -> bool` marks which calls raise."""
    calls = []

    def fake(args, cwd=None):  # noqa: ARG001 - cwd recorded implicitly via calls, not asserted
        calls.append(args)
        if fail_on and fail_on(args):
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args[:2] == ["rev-parse", "HEAD"]:
            return FakeCompletedProcess(stdout=f"{rev_sha}\n")
        return FakeCompletedProcess()

    fake.calls = calls
    return fake


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "CLONE_DIR", tmp_path / "docsite_cache")
    monkeypatch.setattr(m, "_synced_sha", None)


def mark_checkout_present():
    (m.CLONE_DIR / ".git").mkdir(parents=True)


def test_cold_clone_when_no_checkout_exists(monkeypatch):
    git = make_git()
    monkeypatch.setattr(m, "_run_git", git)

    sha = m.sync_docs_repo()

    assert git.calls[0] == [
        "clone",
        "--depth",
        "1",
        "--filter=blob:none",
        "--sparse",
        m.DOCS_REPO_URL,
        str(m.CLONE_DIR),
    ]
    assert git.calls[1] == ["sparse-checkout", "set", *m.DOCS_TYPE_PREFIXES.values()]
    assert sha == FAKE_SHA


def test_sparse_checkout_paths_are_derived_not_hardcoded(monkeypatch):
    monkeypatch.setattr(m, "DOCS_TYPE_PREFIXES", {"made_up_type": "somewhere"})
    git = make_git()
    monkeypatch.setattr(m, "_run_git", git)

    m.sync_docs_repo()

    assert ["sparse-checkout", "set", "somewhere"] in git.calls


def test_warm_update_when_checkout_exists(monkeypatch):
    mark_checkout_present()
    git = make_git()
    monkeypatch.setattr(m, "_run_git", git)

    m.sync_docs_repo()

    assert not any(call[0] == "clone" for call in git.calls)
    assert ["fetch", "--depth", "1", "origin", m.DOCS_REF] in git.calls
    assert ["reset", "--hard", "FETCH_HEAD"] in git.calls


def test_clone_dir_without_git_is_wiped_then_cloned(monkeypatch):
    m.CLONE_DIR.mkdir(parents=True)
    (m.CLONE_DIR / "stale.txt").write_text("leftover")
    git = make_git()
    monkeypatch.setattr(m, "_run_git", git)

    m.sync_docs_repo()

    assert git.calls[0][0] == "clone"
    assert not (m.CLONE_DIR / "stale.txt").exists()


def test_update_failure_serves_stale_checkout(monkeypatch, caplog):
    mark_checkout_present()
    git = make_git(fail_on=lambda args: args[0] == "fetch")
    monkeypatch.setattr(m, "_run_git", git)

    sha = m.sync_docs_repo()

    assert sha == FAKE_SHA
    assert "serving existing" in caplog.text.lower() or "stale" in caplog.text.lower()


def test_clone_failure_with_no_checkout_raises(monkeypatch):
    git = make_git(fail_on=lambda args: args[0] == "clone")
    monkeypatch.setattr(m, "_run_git", git)

    with pytest.raises(ApolloError) as exc_info:
        m.sync_docs_repo()

    assert exc_info.value.code == HTTP_UPSTREAM_ERROR


def test_git_not_on_path_raises_apollo_error(monkeypatch):
    def fake(args, cwd=None):  # noqa: ARG001
        raise FileNotFoundError("git")

    monkeypatch.setattr(m, "_run_git", fake)

    with pytest.raises(ApolloError) as exc_info:
        m.sync_docs_repo()

    assert exc_info.value.code == HTTP_MISCONFIGURED
    assert "git" in exc_info.value.message.lower()


def test_read_markdown_docs_returns_sorted_basenames_and_contents():
    general_dir = m.CLONE_DIR / "docs" / "build"
    general_dir.mkdir(parents=True)
    (general_dir / "zebra.md").write_text("z content")
    (general_dir / "alpha.md").write_text("a content")
    (general_dir / "notes.txt").write_text("ignored, not markdown")

    docs = m.read_markdown_docs("general_docs")

    assert [d["name"] for d in docs] == ["alpha.md", "zebra.md"]
    assert docs[0]["docs"] == "a content"


def test_read_markdown_docs_unknown_type_raises():
    with pytest.raises(ApolloError) as exc_info:
        m.read_markdown_docs("not_a_real_type")

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_read_markdown_docs_raises_when_the_checkout_has_no_markdown():
    (m.CLONE_DIR / "docs").mkdir(parents=True)

    with pytest.raises(ApolloError) as exc_info:
        m.read_markdown_docs("general_docs")

    assert exc_info.value.code == HTTP_MISCONFIGURED
    assert "broken" in exc_info.value.message.lower()


def test_read_markdown_docs_skips_unreadable_files(caplog):
    general_dir = m.CLONE_DIR / "docs"
    general_dir.mkdir(parents=True)
    (general_dir / "good.md").write_text("readable")
    (general_dir / "bad.md").write_bytes(b"\xff\xfe not valid utf-8")

    docs = m.read_markdown_docs("general_docs")

    assert [d["name"] for d in docs] == ["good.md"]
    assert "bad.md" in caplog.text


def test_sync_docs_repo_memoizes_within_a_process(monkeypatch):
    git = make_git()
    monkeypatch.setattr(m, "_run_git", git)

    m.sync_docs_repo()
    calls_after_first = len(git.calls)
    m.sync_docs_repo()

    assert len(git.calls) == calls_after_first
