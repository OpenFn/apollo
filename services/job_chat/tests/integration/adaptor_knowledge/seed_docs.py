"""Dev workaround: populate adaptor_function_docs without running jsdoc.

Only needed on machines where `adaptor_apis` can't generate docs — notably
macOS under bun, where jsdoc dies on `Module.wrapper` (JSDOC_BUN_ERROR.md).
Where the normal pipeline works, job_chat auto-loads on first use and you do
not need this at all.

It reads the pre-built doclet feed that `embed_docsite` already consumes
(OpenFn/adaptors@docs:docs/docs.json), which contains the same jsdoc output
`adaptor_apis` produces, then pushes it through the real ingest functions
(`filter_function_docs` + `upload_to_postgres`). The resulting rows are what
the live pipeline would have written.

The feed only carries each adaptor's LATEST version, so older pins fall back
to the package's published `ast.json` on unpkg. Namespaced operations, which
the feed's doclets don't reliably include, are recovered from the rendered
docs page.

Versions already in the table are left alone — the real pipeline writes richer
rows than these public sources can reconstruct, and `upload_to_postgres`
deletes before inserting. Pass `--force` only when you mean to replace them.

Run it from the repo root with `services/` on the path, the same root
`entry.py` gives services:

    PYTHONPATH=services poetry run python \\
        services/job_chat/tests/integration/adaptor_knowledge/seed_docs.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from load_adaptor_docs.load_adaptor_docs import (
    create_table_if_not_exists,
    filter_function_docs,
    upload_to_postgres,
)
from util import AdaptorSpecifier, get_db_connection

# Same file the repo-root conftest loads, so POSTGRES_URL resolves the same way
# whether this runs standalone or under pytest.
load_dotenv(Path(__file__).resolve().parents[4] / ".env", override=False)

FEED = "https://raw.githubusercontent.com/OpenFn/adaptors/docs/docs/docs.json"


def load_feed():
    with urllib.request.urlopen(FEED, timeout=120) as r:
        return json.load(r)


def _type_names(t):
    """Flatten a doctrine-style type node into jsdoc's `type.names` list."""
    if not t:
        return []
    kind = t.get("type")
    if kind == "NameExpression":
        return [t["name"]]
    if kind in ("UnionType", "TypeUnion"):
        return [n for e in t.get("elements", []) for n in _type_names(e)]
    if kind == "TypeApplication":
        base = _type_names(t.get("expression"))
        args = [n for a in t.get("applications", []) for n in _type_names(a)]
        return [f"{base[0]}.<{','.join(args)}>"] if base else args
    if kind in ("OptionalType", "NullableType", "NonNullableType", "RestType"):
        return _type_names(t.get("expression"))
    return []


def _ast_entry_to_doclet(entry):
    """Reshape one ast.json operation into the jsdoc doclet shape ingest expects."""
    tags = (entry.get("docs") or {}).get("tags") or []
    params = [t for t in tags if t.get("title") == "param"]
    return {
        "kind": "function",
        "access": "public",
        "scope": "global",
        "name": entry["name"],
        "signature": f"{entry['name']}({', '.join(entry.get('params') or [])})",
        "description": (entry.get("docs") or {}).get("description", ""),
        "params": [
            {
                "name": p.get("name"),
                "type": {"names": _type_names(p.get("type"))},
                "optional": bool(p.get("optional")),
                "description": p.get("description") or "",
            }
            for p in params
        ],
        "returns": [
            {"type": {"names": _type_names(t.get("type"))}}
            for t in tags
            if t.get("title") == "returns"
        ],
        "examples": [t.get("description") for t in tags if t.get("title") == "example"],
    }


def namespace_doclets(docs_markdown):
    """Recover namespaced operations from the rendered docs page.

    The feed's doclet list is inconsistent about namespaces — it carries
    dhis2's `tracker.*` and `util.*` but not salesforce's `bulk1.*`/`bulk2.*`.
    The rendered page always has them, as `### bulk2.insert` followed by a
    `<code>insert(sObject, records, [options]) ...</code>` line, which is
    exactly the (function_name, signature) pair the prompt injects.
    """
    text = docs_markdown.encode().decode("unicode_escape")
    doclets = []
    for section in re.split(r"^##\s+", text, flags=re.M)[1:]:
        heading = section.splitlines()[0].strip()
        if heading.lower() in ("functions", "interfaces"):
            continue
        for block in re.split(r"^###\s+", section, flags=re.M)[1:]:
            name = block.splitlines()[0].split("{")[0].strip()
            if "." not in name:
                continue
            scope, _, bare = name.partition(".")
            sig = re.search(r"<code>([^<]+?)</code>", block)
            if not sig:
                continue
            doclets.append({
                "kind": "function",
                "access": "public",
                "scope": scope,
                "name": bare,
                "signature": sig.group(1).split("⇒")[0].strip(),
                "description": "",
                "params": [],
                "returns": [],
                "examples": [],
            })
    return doclets


def load_ast(spec):
    """Per-version fallback: the package's published ast.json, from the CDN.

    The docs feed only carries each adaptor's latest version, so this is the
    only way to seed the old pins the `version` group needs.

    Fidelity note: ast.json lists top-level operations and the re-exported
    common helpers, but NOT namespaced ones (`util.*`, `tracker.*`, `bulk1.*`).
    For the versions we need it for, that's faithful — those namespaces did not
    exist yet. Don't reach for it to seed a modern version.
    """
    pkg, version = spec.rsplit("@", 1)
    url = f"https://unpkg.com/{pkg}@{version}/ast.json"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            ast = json.load(r)
    except Exception as e:
        print(f"skip  {spec} — no ast.json on the CDN ({e})")
        return None

    entries = (ast.get("operations") or []) + (ast.get("common") or [])
    return [_ast_entry_to_doclet(e) for e in entries] or None


def pair_up(feed):
    """The feed alternates {metadata dict} then [jsdoc doclets].

    Doclets are supplemented with namespaced operations recovered from the
    rendered page, which the doclet list doesn't reliably include.
    """
    pairs = {}
    i = 0
    while i < len(feed):
        if isinstance(feed[i], dict):
            meta = feed[i]
            doclets = feed[i + 1] if i + 1 < len(feed) and isinstance(feed[i + 1], list) else None
            if doclets is not None:
                have = {
                    f"{d.get('scope')}.{d.get('name')}"
                    for d in doclets
                    if isinstance(d, dict) and d.get("scope") not in (None, "global")
                }
                extra = [
                    d for d in namespace_doclets(meta.get("docs", ""))
                    if f"{d['scope']}.{d['name']}" not in have
                ]
                pairs[f"{meta['adaptor']}@{meta['version']}"] = doclets + extra
                i += 2
                continue
        i += 1
    return pairs


def existing_count(conn, spec):
    adaptor = AdaptorSpecifier(spec)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM adaptor_function_docs WHERE adaptor_name = %s AND version = %s",
            (adaptor.name, adaptor.version),
        )
        return cur.fetchone()[0]


def main(wanted, force=False):
    """Seed any wanted version that isn't already present.

    Existing rows are left alone unless `force`. `upload_to_postgres` deletes
    before inserting, so re-seeding a version that the real pipeline populated
    would replace richer rows (namespaced functions, full param docs) with
    whatever these public sources can reconstruct. Don't.
    """
    feed = pair_up(load_feed())
    conn = get_db_connection()
    try:
        create_table_if_not_exists(conn)
        for spec in wanted:
            present = existing_count(conn, spec)
            if present and not force:
                print(f"have  {spec} — {present} functions already, leaving it alone")
                continue

            doclets, source = feed.get(spec), "feed"
            if doclets is None:
                doclets, source = load_ast(spec), "ast.json"
            if doclets is None:
                continue

            adaptor = AdaptorSpecifier(spec)
            docs = filter_function_docs(doclets)
            upload_to_postgres(adaptor, docs, conn)
            print(f"seed  {spec} — {len(docs)} functions (via {source})")
    finally:
        conn.close()


if __name__ == "__main__":
    from job_chat.tests.integration.adaptor_knowledge.cases import ALL_CASES

    argv = [a for a in sys.argv[1:] if a != "--force"]
    targets = argv or sorted({c.adaptor for c in ALL_CASES})
    main(targets, force="--force" in sys.argv[1:])
