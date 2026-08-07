"""Offline recall@k + latency comparison between docsite search backends.

Usage: poetry run python -m search_docsite.tests.eval.run_eval

Compares the Postgres-backed DocsiteSearch against LegacyPineconeDocsiteSearch
over the golden query set. Both run strategy='semantic'.

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


def print_per_query_results(postgres_report, pinecone_report):
    """Print each golden query's expected titles and both backends' hit/miss + retrieved titles."""
    print("\nPer-query results:")
    for pg, pc in zip(postgres_report["per_query"], pinecone_report["per_query"], strict=True):
        expected = ", ".join(pg["expected_titles"]) or "(unlabelled — excluded from recall)"
        print(f"  {pg['query']}")
        print(f"    expected: {expected}")
        for name, report_item in (("postgres", pg), ("pinecone", pc)):
            status = {True: "HIT ", False: "MISS", None: "--  "}[report_item["hit"]]
            titles = ", ".join(t for t in report_item["retrieved_titles"] if t is not None)
            print(f"    {name:8} {status}  {report_item['latency_s']:.3f}s  {titles}")


def main():
    with open(GOLDEN_QUERIES_PATH) as f:
        golden_queries = yaml.safe_load(f)["queries"]

    postgres_report = run_eval(golden_queries, DocsiteSearch, strategy="semantic")
    pinecone_report = run_eval(golden_queries, LegacyPineconeDocsiteSearch, strategy="semantic")

    print(f"Postgres (semantic): recall@5={postgres_report['recall_at_k']} "
          f"(scored={postgres_report['queries_scored']}, skipped={postgres_report['queries_skipped']}) "
          f"p50={postgres_report['p50_latency_s']:.3f}s p95={postgres_report['p95_latency_s']:.3f}s")
    print(f"Pinecone (semantic): recall@5={pinecone_report['recall_at_k']} "
          f"(scored={pinecone_report['queries_scored']}, skipped={pinecone_report['queries_skipped']}) "
          f"p50={pinecone_report['p50_latency_s']:.3f}s p95={pinecone_report['p95_latency_s']:.3f}s")

    agreement = compute_agreement(postgres_report, pinecone_report)
    print(f"Backend agreement:   mean doc-title Jaccard={agreement['mean_jaccard']:.3f} "
          f"across {len(agreement['per_query'])} queries")
    for q in agreement["per_query"]:
        print(f"  {q['jaccard']:.2f}  overlap={q['overlap']}/{q['union']}  {q['query']}")

    print_per_query_results(postgres_report, pinecone_report)


if __name__ == "__main__":
    main()
