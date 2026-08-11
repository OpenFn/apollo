"""On-disk cache of the OpenFn docs corpus.

Follows services/latest_adaptors/latest_adaptors.py: the cache lives beside the
module, is gitignored, is written atomically, and — the property that actually
matters — is served when the fetch fails. A GitHub rate limit then degrades to
slightly stale docs instead of failing the run.

Refreshing and reading are separate concerns: `refresh_cache` brings the whole
corpus up to date, then `read_docs` serves each docs_type from disk without
touching the network.

Freshness is decided by upstream state, not a clock: one conditional Trees
request per run, and a per-file blob SHA comparison, so an unchanged corpus
downloads nothing.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from embed_docsite.github_utils import (
    DOCS_REF,
    DOCS_REPO,
    DOCS_TYPE_PREFIXES,
    download_file,
    get_adaptor_function_docs,
    get_repo_tree,
    markdown_paths,
)
from util import ApolloError, create_logger

logger = create_logger("DocsiteCache")

CACHE_DIR = Path(__file__).parent / "docsite_cache"
ADAPTOR_FUNCTIONS_FILE = "adaptor_functions.json"

# One key per repo: general_docs and adaptor_docs both come from OpenFn/docs, so
# one tree read and one manifest entry cover both.
REPO_KEY = f"{DOCS_REPO}@{DOCS_REF}"


def _manifest_path():
    """Derived at call time so tests only need to patch CACHE_DIR."""
    return CACHE_DIR / "manifest.json"


def load_manifest():
    """The manifest, or {} if missing or unreadable."""
    path = _manifest_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"Failed to read docsite cache manifest: {exc}")
        return {}


def write_manifest(manifest):
    """Atomic, so a reader never sees a half-written manifest."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _manifest_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_cached_file(relative_path, text):
    dest = CACHE_DIR / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)


def _read_cached_file(relative_path):
    return (CACHE_DIR / relative_path).read_text(encoding="utf-8")


def _now():
    return datetime.now(UTC).isoformat()


def is_populated():
    """True when the markdown corpus has been cached at least once."""
    return bool(load_manifest().get(REPO_KEY, {}).get("files"))


def refresh_markdown_cache():
    """Bring the cached OpenFn/docs markdown up to date.

    Costs one conditional Trees request, and covers every markdown docs_type in
    that one call. An unchanged upstream answers 304, which carries no body and
    downloads nothing. A change downloads only the blobs whose SHA moved.

    :return: number of files downloaded
    """
    manifest = load_manifest()
    entry = manifest.get(REPO_KEY, {})

    tree = get_repo_tree(etag=entry.get("etag"))
    if tree is None:
        return 0

    wanted = {}
    for docs_type in DOCS_TYPE_PREFIXES:
        for path in markdown_paths(tree["files"], docs_type):
            wanted[path] = tree["files"][path]

    cached = entry.get("files", {})
    downloaded = 0
    for path, sha in sorted(wanted.items()):
        if cached.get(path) == sha and (CACHE_DIR / path).exists():
            continue
        _write_cached_file(path, download_file(path))
        downloaded += 1

    for removed in set(cached) - set(wanted):
        (CACHE_DIR / removed).unlink(missing_ok=True)

    manifest[REPO_KEY] = {
        "tree_sha": tree["tree_sha"],
        "etag": tree["etag"],
        "fetched_at": _now(),
        "files": wanted,
    }
    write_manifest(manifest)
    logger.info(f"Docs cache refreshed, {downloaded} file(s) downloaded")
    return downloaded


def refresh_adaptor_functions_cache():
    """Refresh the adaptor function docs JSON. Returns True if it changed."""
    manifest = load_manifest()
    result = get_adaptor_function_docs(etag=manifest.get("adaptor_functions", {}).get("etag"))
    if result is None:
        return False

    _write_cached_file(ADAPTOR_FUNCTIONS_FILE, json.dumps(result["docs"]))
    manifest["adaptor_functions"] = {"etag": result["etag"], "fetched_at": _now()}
    write_manifest(manifest)
    logger.info("Adaptor function docs cache refreshed")
    return True


def _no_cache_error(docs_types, reason):
    """The one way this module reports 'nothing to serve'.

    An ApolloError carries a code that bridge.ts maps to an HTTP status; a bare
    FileNotFoundError escaping from a read would not.

    :param docs_types: the docs type(s) this concerns, named as the payload does
    """
    return ApolloError(
        503,
        f"Could not fetch {docs_types} from GitHub and no cached copy exists: {reason}",
        type="UPSTREAM_ERROR",
    )


def _survive_or_raise(exc, have_cache, docs_types):
    """A refresh failure is survivable only when something is already cached."""
    if have_cache:
        logger.warning(f"Could not refresh {docs_types}, serving cached copy: {exc}")
        return
    raise _no_cache_error(docs_types, exc)


def refresh_cache(docs_types):
    """Bring the cache up to date for the requested docs types.

    Call once per run, before reading. The markdown refresh covers every
    markdown docs_type in a single conditional Trees request, so the number of
    docs types requested does not change the cost.

    Only the requested types are refreshed: a run wanting just adaptor_functions
    leaves the markdown corpus alone.

    :return: {"markdown_files_downloaded": int, "adaptor_functions_updated": bool}
    """
    downloaded = 0
    updated = False

    markdown_types = [docs_type for docs_type in docs_types if docs_type in DOCS_TYPE_PREFIXES]
    if markdown_types:
        try:
            downloaded = refresh_markdown_cache()
        except Exception as exc:
            _survive_or_raise(exc, is_populated(), ", ".join(markdown_types))

    if "adaptor_functions" in docs_types:
        try:
            updated = refresh_adaptor_functions_cache()
        except Exception as exc:
            _survive_or_raise(exc, (CACHE_DIR / ADAPTOR_FUNCTIONS_FILE).exists(), "adaptor_functions")

    return {"markdown_files_downloaded": downloaded, "adaptor_functions_updated": updated}


def read_docs(docs_type):
    """Docs for one docs_type, served from disk. Never touches the network.

    Refresh first with refresh_cache; an unpopulated cache raises rather than
    reporting the docs as empty.

    Return contract matches the get_docs that DocsiteProcessor depends on.
    """
    if docs_type == "adaptor_functions":
        # The manifest decided we could degrade; only the disk can confirm it. A
        # 304 leaves the etag current even if the file underneath was deleted.
        if not (CACHE_DIR / ADAPTOR_FUNCTIONS_FILE).exists():
            raise _no_cache_error(docs_type, "the cached file is missing from disk")
        return json.loads(_read_cached_file(ADAPTOR_FUNCTIONS_FILE))

    if docs_type not in DOCS_TYPE_PREFIXES:
        raise ApolloError(400, f"Unknown docs_type '{docs_type}'", type="BAD_REQUEST")

    if not is_populated():
        raise _no_cache_error(docs_type, "the cache is empty; refresh_cache must run first")

    paths = markdown_paths(load_manifest().get(REPO_KEY, {}).get("files", {}), docs_type)
    present = [path for path in paths if (CACHE_DIR / path).exists()]

    if len(present) < len(paths):
        logger.warning(f"{len(paths) - len(present)} cached {docs_type} file(s) missing from disk, skipped")
    if paths and not present:
        # Returning [] here would index an empty corpus and call it the docs.
        raise _no_cache_error(docs_type, "every cached file is missing from disk")

    return [{"name": Path(path).name, "docs": _read_cached_file(path)} for path in present]
