"""Offline recall@k + latency comparison between docsite search backends.

Usage: poetry run python -m search_docsite.tests.eval.run_eval

Compares Postgres semantic and hybrid search at each indexed chunk size against
the legacy Pinecone baseline, over the golden query set. Recall is reported per
query category, because hybrid is expected to help on keyword lookups and tie on
conceptual ones — a blended figure would hide that.

Requires a Postgres batch per chunk size in CHUNK_SIZES; configurations without
one are skipped. Index them with embed_docsite, passing chunk_target_length,
chunk_min_length, and keep_batches >= 3 so earlier batches are not pruned.

Golden queries live in services/search_docsite/tests/eval/golden_queries.yaml
— edit that file to add queries or curate expected_doc_titles.
"""

import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Needed as LegacyPineconeDocsiteSearch evaluates OpenAIEmbeddings() as a 
# default argument.
load_dotenv()

from search_docsite.pinecone_legacy_search import LegacyPineconeDocsiteSearch
from search_docsite.search_docsite import DocsiteSearch
from util import get_db_connection

GOLDEN_QUERIES_PATH = Path(__file__).parent / "golden_queries.yaml"

# Chunk sizes to evaluate, matching docsite_batches.chunk_target_length.
CHUNK_SIZES = [1000, 1800, 2500]
STRATEGIES = ["semantic", "hybrid"]

# The migration-fidelity pairing: same strategy and chunk size, different store.
AGREEMENT_PAIR = ("Pinecone semantic", "Postgres semantic (1000)")


def resolve_batch_id(chunk_target_length):
    """Newest complete batch indexed at the given chunk size, or None if there is none.

    Batch ids are environment-specific, so the eval looks them up by the indexing
    configuration recorded on each batch rather than hardcoding them.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM docsite_batches WHERE status = 'complete' "
                "AND chunk_target_length = %s ORDER BY id DESC LIMIT 1",
                (chunk_target_length,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    return row[0] if row else None


def compute_recall_at_k(retrieved_titles, expected_titles):
    """True if any expected title appears among the retrieved titles."""
    return bool(set(retrieved_titles) & set(expected_titles))


def compute_agreement(report_a, report_b):
    """Doc-title overlap between two backends' result sets, per query and averaged.

    Needs no ground truth, so it gives a usable comparison signal before
    golden_queries.yaml is curated.
    """
    per_query = []
    for a, b in zip(report_a["per_query"], report_b["per_query"], strict=True):
        titles_a = {t for t in a["retrieved_titles"] if t is not None}
        titles_b = {t for t in b["retrieved_titles"] if t is not None}
        union = titles_a | titles_b
        overlap = titles_a & titles_b
        per_query.append({
            "query": a["query"],
            "overlap": len(overlap),
            "union": len(union),
            "jaccard": (len(overlap) / len(union)) if union else 0.0,
        })

    mean_jaccard = (sum(q["jaccard"] for q in per_query) / len(per_query)) if per_query else 0.0
    return {"per_query": per_query, "mean_jaccard": mean_jaccard}


def run_eval(golden_queries, make_backend, strategy, top_k=5):
    """Run every golden query against one backend/strategy and return a report dict."""
    backend = make_backend()
    per_query = []
    latencies = []
    scored = 0
    skipped = 0
    hits = 0
    by_category = {}

    for item in golden_queries:
        query = item["query"]
        expected_titles = item.get("expected_doc_titles", [])
        category = item.get("category")

        start = time.time()
        results = backend.search(query, top_k=top_k, strategy=strategy, docs_type="general_docs")
        elapsed = time.time() - start
        latencies.append(elapsed)

        retrieved_titles = [r.metadata.get("doc_title") for r in results]

        if expected_titles:
            hit = compute_recall_at_k(retrieved_titles, expected_titles)
            scored += 1
            hits += int(hit)
            if category:
                counts = by_category.setdefault(category, {"scored": 0, "hits": 0})
                counts["scored"] += 1
                counts["hits"] += int(hit)
        else:
            hit = None
            skipped += 1

        per_query.append({
            "query": query,
            "category": category,
            "retrieved_titles": retrieved_titles,
            "expected_titles": expected_titles,
            "hit": hit,
            "latency_s": elapsed,
        })

    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0.0
    p95_index = min(len(latencies_sorted) - 1, int(len(latencies_sorted) * 0.95)) if latencies_sorted else 0
    p95 = latencies_sorted[p95_index] if latencies_sorted else 0.0

    return {
        "recall_at_k": (hits / scored) if scored else None,
        "recall_by_category": {
            name: {"recall": c["hits"] / c["scored"], "scored": c["scored"]}
            for name, c in sorted(by_category.items())
        },
        "queries_scored": scored,
        "queries_skipped": skipped,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "per_query": per_query,
    }


def print_per_query_results(label_a, report_a, label_b, report_b):
    """Print each golden query's expected titles and both backends' hit/miss + retrieved titles."""
    print("\nPer-query results:")
    for a, b in zip(report_a["per_query"], report_b["per_query"], strict=True):
        expected = ", ".join(a["expected_titles"]) or "(unlabelled — excluded from recall)"
        print(f"  [{a['category'] or 'uncategorised'}] {a['query']}")
        print(f"    expected: {expected}")
        for label, item in ((label_a, a), (label_b, b)):
            status = {True: "HIT ", False: "MISS", None: "--  "}[item["hit"]]
            titles = ", ".join(t for t in item["retrieved_titles"] if t is not None)
            print(f"    {label:26} {status}  {item['latency_s']:.3f}s  {titles}")


def build_configs():
    """Every (label, backend factory, strategy) to evaluate.

    Postgres configurations for a chunk size with no complete batch are skipped
    with a notice, so the eval still runs when only some batches are indexed.
    """
    configs = [("Pinecone semantic", LegacyPineconeDocsiteSearch, "semantic")]

    for chunk_size in CHUNK_SIZES:
        batch_id = resolve_batch_id(chunk_size)
        if batch_id is None:
            print(f"Skipping Postgres configs for chunk size {chunk_size} — no complete batch")
            continue
        for strategy in STRATEGIES:
            label = f"Postgres {strategy} ({chunk_size})"
            configs.append((label, lambda b=batch_id: DocsiteSearch(batch_id=b), strategy))

    return configs


def _fmt(recall):
    """Render a recall figure, or a dash when the category had no scored queries."""
    return "-" if recall is None else f"{recall:.2f}"


def main():
    with open(GOLDEN_QUERIES_PATH) as f:
        golden_queries = yaml.safe_load(f)["queries"]

    reports = {}
    for label, make_backend, strategy in build_configs():
        reports[label] = run_eval(golden_queries, make_backend, strategy)

    print(f"\n{'configuration':<28} {'conceptual':>11} {'keyword':>9} {'overall':>9} {'p50':>8} {'p95':>8}")
    for label, report in reports.items():
        by_cat = report["recall_by_category"]
        conceptual = by_cat.get("conceptual", {}).get("recall")
        keyword = by_cat.get("keyword", {}).get("recall")
        print(f"{label:<28} "
              f"{_fmt(conceptual):>11} {_fmt(keyword):>9} {_fmt(report['recall_at_k']):>9} "
              f"{report['p50_latency_s']:>7.3f}s {report['p95_latency_s']:>7.3f}s")

    scored = next(iter(reports.values()))
    print(f"\nScored {scored['queries_scored']} queries, skipped {scored['queries_skipped']}")

    label_a, label_b = AGREEMENT_PAIR
    if label_a in reports and label_b in reports:
        agreement = compute_agreement(reports[label_a], reports[label_b])
        print(f"\nMigration fidelity ({label_a} vs {label_b}):")
        print(f"  mean doc-title Jaccard={agreement['mean_jaccard']:.3f} "
              f"across {len(agreement['per_query'])} queries")
        for q in agreement["per_query"]:
            print(f"  {q['jaccard']:.2f}  overlap={q['overlap']}/{q['union']}  {q['query']}")
        print_per_query_results(label_a, reports[label_a], label_b, reports[label_b])


if __name__ == "__main__":
    main()
