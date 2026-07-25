"""Unit tests for the offline golden-query eval's scoring logic.
Backends are fully faked — no real search/DB/network involved."""

from unittest.mock import MagicMock

from search_docsite.tests.eval.run_eval import compute_recall_at_k, run_eval


def test_compute_recall_at_k_true_when_any_expected_title_present():
    assert compute_recall_at_k(["Doc A", "Doc B"], ["Doc B", "Doc C"]) is True


def test_compute_recall_at_k_false_when_no_overlap():
    assert compute_recall_at_k(["Doc A"], ["Doc Z"]) is False


def make_fake_backend(titles_by_query):
    """Fake backend whose .search() returns SearchResults with the given doc_titles per query."""
    from embeddings.embeddings import SearchResult

    def fake_search(query, top_k=None, strategy=None, docs_type=None):
        return [SearchResult(f"text-{t}", {"doc_title": t, "docs_type": "general_docs"}, 0.9) for t in titles_by_query.get(query, [])]

    backend = MagicMock()
    backend.search.side_effect = fake_search
    backend_cls = MagicMock(return_value=backend)
    return backend_cls


def test_run_eval_scores_labeled_queries_and_skips_unlabeled():
    golden_queries = [
        {"query": "how do I configure a webhook", "expected_doc_titles": ["Webhooks"]},
        {"query": "what is a run", "expected_doc_titles": []},  # unlabeled — skipped from recall aggregate
    ]
    backend_cls = make_fake_backend({"how do I configure a webhook": ["Webhooks", "Other Doc"], "what is a run": ["Runs"]})

    report = run_eval(golden_queries, backend_cls, strategy="hybrid", top_k=5)

    assert report["queries_scored"] == 1
    assert report["queries_skipped"] == 1
    assert report["recall_at_k"] == 1.0
    assert len(report["per_query"]) == 2


def test_run_eval_computes_recall_across_multiple_labeled_queries():
    golden_queries = [
        {"query": "q1", "expected_doc_titles": ["A"]},
        {"query": "q2", "expected_doc_titles": ["Z"]},  # backend won't return Z -> miss
    ]
    backend_cls = make_fake_backend({"q1": ["A"], "q2": ["B"]})

    report = run_eval(golden_queries, backend_cls, strategy="semantic", top_k=5)

    assert report["queries_scored"] == 2
    assert report["recall_at_k"] == 0.5


def test_run_eval_reports_latency_percentiles():
    golden_queries = [{"query": "q1", "expected_doc_titles": ["A"]}]
    backend_cls = make_fake_backend({"q1": ["A"]})

    report = run_eval(golden_queries, backend_cls, strategy="hybrid", top_k=5)

    assert "p50_latency_s" in report
    assert "p95_latency_s" in report
    assert report["p50_latency_s"] >= 0
