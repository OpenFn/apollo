"""Offline recall@k + latency comparison between docsite search backends.

Usage: poetry run python -m search_docsite.tests.eval.run_eval

Compares the Postgres-backed DocsiteSearch (strategy='hybrid') against
LegacyPineconeDocsiteSearch (strategy='semantic') over the golden query set,
per the Phase-1 shadow-mode rollout plan: Postgres must match or beat
Pinecone's recall@5 (with <=1-query regression tolerance) and p95 latency
before DOCSITE_SEARCH_BACKEND is flipped to 'postgres' by default.
"""

import time
from pathlib import Path

import yaml
from search_docsite.pinecone_legacy_search import LegacyPineconeDocsiteSearch
from search_docsite.search_docsite import DocsiteSearch

GOLDEN_QUERIES_PATH = Path(__file__).parent / "golden_queries.yaml"


def compute_recall_at_k(retrieved_titles, expected_titles):
    """True if any expected title appears among the retrieved titles."""
    return bool(set(retrieved_titles) & set(expected_titles))


def compute_agreement(report_a, report_b):
    """Doc-title overlap between two backends' result sets, per query and averaged.

    Needs no ground truth, so it gives a usable comparison signal before
    golden_queries.yaml is curated. This is the measure the deleted shadow mode
    computed on live traffic; it belongs here, offline, instead.
    """
    per_query = []
    for a, b in zip(report_a["per_query"], report_b["per_query"]):
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


def run_eval(golden_queries, backend_cls, strategy, top_k=5):
    """Run every golden query against one backend/strategy and return a report dict."""
    backend = backend_cls()
    per_query = []
    latencies = []
    scored = 0
    skipped = 0
    hits = 0

    for item in golden_queries:
        query = item["query"]
        expected_titles = item.get("expected_doc_titles", [])

        start = time.time()
        results = backend.search(query, top_k=top_k, strategy=strategy, docs_type="general_docs")
        elapsed = time.time() - start
        latencies.append(elapsed)

        retrieved_titles = [r.metadata.get("doc_title") for r in results]

        if expected_titles:
            hit = compute_recall_at_k(retrieved_titles, expected_titles)
            scored += 1
            hits += int(hit)
        else:
            hit = None
            skipped += 1

        per_query.append({
            "query": query,
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
        "queries_scored": scored,
        "queries_skipped": skipped,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "per_query": per_query,
    }


def main():
    with open(GOLDEN_QUERIES_PATH) as f:
        golden_queries = yaml.safe_load(f)["queries"]

    postgres_report = run_eval(golden_queries, DocsiteSearch, strategy="hybrid")
    pinecone_report = run_eval(golden_queries, LegacyPineconeDocsiteSearch, strategy="semantic")

    print(f"Postgres (hybrid):  recall@5={postgres_report['recall_at_k']} "
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


if __name__ == "__main__":
    main()
