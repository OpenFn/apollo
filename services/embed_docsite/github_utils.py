"""Fetches the OpenFn docs corpus.

Markdown docs come from a shallow, blobless, sparse `git clone` of OpenFn/docs
kept at `CLONE_DIR`; adaptor function docs come from a prebuilt JSON file over
HTTP. `sync_docs_repo` clones on the first call in a process and `fetch`+`reset
--hard`s after. A failed refresh serves the existing checkout rather than
failing the run.
"""

import shutil
import subprocess
from functools import cache
from pathlib import Path

import requests
from util import ApolloError, create_logger

logger = create_logger("GitHubUtils")

DOCS_REPO_URL = "https://github.com/OpenFn/docs.git"
DOCS_REF = "main"
CLONE_DIR = Path(__file__).parent / "docsite_cache"

# Which top-level directory in OpenFn/docs backs each docs_type.
DOCS_TYPE_PREFIXES = {"general_docs": "docs", "adaptor_docs": "adaptors"}

GIT_TIMEOUT_SECONDS = 300


def get_docs(docs_type):
    """Docs for one docs_type. The entry point for this module."""
    if docs_type == "adaptor_functions":
        return get_adaptor_function_docs()
    sync_docs_repo()
    return read_markdown_docs(docs_type)


@cache
def sync_docs_repo():
    """Bring the checkout up to date. Call once per run, before reading.

    Memoized per process: one run reads both markdown docs_types and they
    should cost one sync, not two.

    :return: the checkout's HEAD sha
    """
    have_checkout = (CLONE_DIR / ".git").exists()

    try:
        update() if have_checkout else wipe_and_clone()
    except FileNotFoundError as exc:
        raise ApolloError(
            500,
            f"git is required to fetch the docs corpus but is not on PATH: {exc}",
            type="MISCONFIGURED",
        ) from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        if have_checkout:
            logger.warning(f"Could not refresh the docs checkout, serving existing copy: {exc}")
            return head_sha()
        raise ApolloError(
            503,
            f"Could not clone the docs repo and no cached checkout exists: {exc}",
            type="UPSTREAM_ERROR",
        ) from exc

    return head_sha()


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


def get_adaptor_function_docs(data_url="https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"):
    """Fetches adaptor data from the preprocessed adaptor docs url."""
    try:
        response = requests.get(data_url)
        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:
        logger.error(f"Failed to fetch data: {e}")


def run_git(args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def wipe_and_clone():
    """Wipe CLONE_DIR and clone into it. Also the recovery path for a corrupt checkout.

    Blobless and sparse: the rest of OpenFn/docs is images and static assets we
    never index, so their blobs are never transferred.
    """
    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    run_git(["clone", "--depth", "1", "--filter=blob:none", "--sparse", DOCS_REPO_URL, str(CLONE_DIR)])
    run_git(["sparse-checkout", "set", *DOCS_TYPE_PREFIXES.values()], cwd=CLONE_DIR)
    logger.info(f"Cloned {DOCS_REPO_URL} to {CLONE_DIR}")


def update():
    run_git(["fetch", "--depth", "1", "origin", DOCS_REF], cwd=CLONE_DIR)
    run_git(["reset", "--hard", "FETCH_HEAD"], cwd=CLONE_DIR)
    logger.info("Docs checkout updated")


def head_sha():
    result = run_git(["rev-parse", "HEAD"], cwd=CLONE_DIR)
    return result.stdout.strip()
