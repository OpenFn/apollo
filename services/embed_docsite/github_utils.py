import os
from datetime import UTC, datetime

import requests
from util import ApolloError, create_logger

logger = create_logger("GitHubUtils")

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

DOCS_REPO = "OpenFn/docs"
DOCS_REF = "main"

# Which top-level path in OpenFn/docs backs each docs_type.
DOCS_TYPE_PREFIXES = {"general_docs": "docs/", "adaptor_docs": "adaptors/"}

ADAPTOR_FUNCTIONS_URL = f"{GITHUB_RAW}/OpenFn/adaptors/docs/docs/docs.json"

REQUEST_TIMEOUT_SECONDS = 30

HTTP_NOT_MODIFIED = 304
HTTP_FORBIDDEN = 403

# GitHub reports the remaining quota as a decimal string in X-RateLimit-Remaining.
RATE_LIMIT_EXHAUSTED = "0"


def _github_headers(etag=None):
    """Headers for an api.github.com request.

    A token lifts the rate limit from 60 to 5000 requests/hour. An
    `If-None-Match` makes revalidation cheap, not free: a 304 still costs the
    same one request against the limit as a 200 would, but carries no body.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if etag:
        headers["If-None-Match"] = etag
    return headers


def _raise_if_rate_limited(response):
    """Turn GitHub's rate-limit 403 into an error that says 'rate limit'.

    This path used to return silently, leaving the caller to fail later with
    `IndexError: list index out of range` — which named neither the cause nor
    the fix.
    """
    if response.status_code != HTTP_FORBIDDEN or response.headers.get("X-RateLimit-Remaining") != RATE_LIMIT_EXHAUSTED:
        return

    reset = response.headers.get("X-RateLimit-Reset")
    when = ""
    if reset:
        resets_at = datetime.fromtimestamp(int(reset), tz=UTC).isoformat()
        when = f" Resets at {resets_at}."

    raise ApolloError(
        429,
        f"GitHub API rate limit exceeded.{when} Set GITHUB_TOKEN to raise the limit "
        "from 60 to 5000 requests/hour",
        type="RATE_LIMITED",
    )


def get_repo_tree(repo=DOCS_REPO, ref=DOCS_REF, etag=None):
    """Fetch a repository's entire file tree in one request.

    Replaces a recursive contents-API walk that cost one request per directory
    (~22 for OpenFn/docs).

    :param etag: if supplied and still current, GitHub answers 304 and this
        returns None — meaning the caller's cache is up to date. The request
        still spends one unit of rate limit; what it saves is the response body
        and every file download the caller would otherwise have made.
    :return: {"tree_sha", "etag", "files": {path: blob_sha}}, or None if unchanged
    """
    url = f"{GITHUB_API}/repos/{repo}/git/trees/{ref}?recursive=1"
    response = requests.get(url, headers=_github_headers(etag), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == HTTP_NOT_MODIFIED:
        logger.info(f"{repo} tree unchanged upstream")
        return None

    _raise_if_rate_limited(response)
    response.raise_for_status()
    payload = response.json()

    if payload.get("truncated"):
        raise ApolloError(
            500,
            f"GitHub returned a truncated tree for {repo}; it can no longer be listed in one call",
            type="UPSTREAM_ERROR",
        )

    files = {item["path"]: item["sha"] for item in payload.get("tree", []) if item.get("type") == "blob"}
    logger.info(f"Read {repo}@{ref} tree, {len(files)} files")
    return {"tree_sha": payload["sha"], "etag": response.headers.get("ETag"), "files": files}


def raw_url(path, repo=DOCS_REPO, ref=DOCS_REF):
    """Build a raw.githubusercontent URL.

    The Trees API supplies no download_url, and raw.githubusercontent is not
    subject to the API rate limit. `ref` must match the ref the tree was read at,
    or the bytes won't correspond to the blob SHA recorded against them.
    """
    return f"{GITHUB_RAW}/{repo}/{ref}/{path}"


def download_file(path, repo=DOCS_REPO, ref=DOCS_REF):
    """Download one file's text. Not rate-limited."""
    response = requests.get(raw_url(path, repo, ref), timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def get_adaptor_function_docs(etag=None):
    """Fetch the preprocessed adaptor docs JSON.

    Served from raw.githubusercontent, so no API rate limit applies, but it does
    honour ETags — a warm cache revalidates without transferring the body.

    :return: {"docs": <parsed json>, "etag": str | None}, or None if unchanged
    """
    headers = {"If-None-Match": etag} if etag else {}
    response = requests.get(ADAPTOR_FUNCTIONS_URL, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == HTTP_NOT_MODIFIED:
        logger.info("Adaptor function docs unchanged upstream")
        return None

    response.raise_for_status()
    return {"docs": response.json(), "etag": response.headers.get("ETag")}


def markdown_paths(tree_files, docs_type):
    """The .md paths in a tree that belong to one docs_type, sorted."""
    prefix = DOCS_TYPE_PREFIXES[docs_type]
    return sorted(p for p in tree_files if p.startswith(prefix) and p.endswith(".md"))
