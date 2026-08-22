"""A shallow, blobless, sparse git checkout of OpenFn/docs, kept on disk.

Uses a single `git clone`/`fetch`.

`sync_docs_repo` clones on the first call in a process and `fetch`+`reset
--hard`s on every call after, memoized. A failed refresh serves the
existing checkout rather than failing the run, same as
`services/latest_adaptors/latest_adaptors.py`'s cache.

The clone is blobless and sparse-checked-out to only `DOCS_TYPE_PREFIXES`'
directories, so the missing blobs are fetched lazily for the checkout.
"""

import shutil
import subprocess
from pathlib import Path

from util import ApolloError, create_logger

logger = create_logger("DocsRepo")

DOCS_REPO_URL = "https://github.com/OpenFn/docs.git"
DOCS_REF = "main"
CLONE_DIR = Path(__file__).parent / "docsite_cache"

# Which top-level directory in OpenFn/docs backs each docs_type.
DOCS_TYPE_PREFIXES = {"general_docs": "docs", "adaptor_docs": "adaptors"}

GIT_TIMEOUT_SECONDS = 300

# Memoized per process: a full run reads two docs_types, and they should
# cost one sync, not two.
_synced_sha = None


def _run_git(args, cwd=None):
    """Subprocess seam."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _has_checkout():
    return (CLONE_DIR / ".git").exists()


def _clone():
    """Wipe and clone. Also the recovery path for a corrupt or partial checkout.

    Blobless (`--filter=blob:none`) and sparse, checked out to only the
    directories `DOCS_TYPE_PREFIXES` names: the rest of OpenFn/docs is images
    and static assets we never index, and this way their blobs are never even
    transferred. `sparse-checkout set` fetches the blobs it needs to
    materialize those paths as part of running; nothing later in this module
    reads outside them, so no further blob fetch happens after this call.
    """
    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    _run_git(["clone", "--depth", "1", "--filter=blob:none", "--sparse", DOCS_REPO_URL, str(CLONE_DIR)])
    _run_git(["sparse-checkout", "set", *DOCS_TYPE_PREFIXES.values()], cwd=CLONE_DIR)
    logger.info(f"Cloned {DOCS_REPO_URL} to {CLONE_DIR}")


def _update():
    _run_git(["fetch", "--depth", "1", "origin", DOCS_REF], cwd=CLONE_DIR)
    _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=CLONE_DIR)
    logger.info("Docs checkout updated")


def _head_sha():
    result = _run_git(["rev-parse", "HEAD"], cwd=CLONE_DIR)
    return result.stdout.strip()


def sync_docs_repo():
    """Bring the checkout up to date. Call once per run, before reading.

    :return: the checkout's HEAD sha
    """
    global _synced_sha  # noqa: PLW0603 - per-process memo, same pattern as util.py's apollo_port

    if _synced_sha is not None:
        return _synced_sha

    have_checkout = _has_checkout()

    try:
        _update() if have_checkout else _clone()
    except FileNotFoundError as exc:
        raise ApolloError(
            500,
            f"git is required to fetch the docs corpus but is not on PATH: {exc}",
            type="MISCONFIGURED",
        ) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if have_checkout:
            logger.warning(f"Could not refresh the docs checkout, serving existing copy: {exc}")
            _synced_sha = _head_sha()
            return _synced_sha
        raise ApolloError(
            503,
            f"Could not clone the docs repo and no cached checkout exists: {exc}",
            type="UPSTREAM_ERROR",
        ) from exc

    _synced_sha = _head_sha()
    return _synced_sha


def read_markdown_docs(docs_type):
    """Markdown docs for one docs_type, read from the checkout on disk.

    Calls `sync_docs_repo` first.

    :return: [{"name": <basename>, "docs": <text>}], sorted by path
    """
    if docs_type not in DOCS_TYPE_PREFIXES:
        raise ApolloError(400, f"Unknown docs_type '{docs_type}'", type="BAD_REQUEST")

    prefix_dir = CLONE_DIR / DOCS_TYPE_PREFIXES[docs_type]
    paths = sorted(prefix_dir.rglob("*.md"))
    if not paths:
        raise ApolloError(
            500,
            f"No markdown files under {prefix_dir}; the docs checkout may be broken",
            type="INTERNAL_ERROR",
        )

    docs = []
    for path in paths:
        try:
            docs.append({"name": path.name, "docs": path.read_text(encoding="utf-8")})
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Skipping {path}: {exc}")
    return docs
