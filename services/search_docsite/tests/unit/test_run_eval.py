"""Unit tests for the offline golden-query eval's scoring logic.
Backends are fully faked — no real search/DB/network involved."""

from unittest.mock import MagicMock

import pytest
from search_docsite.tests.eval.run_eval import compute_agreement, compute_recall_at_k, run_eval


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


def test_compute_agreement_reports_perfect_overlap():
    report_a = {"per_query": [{"query": "q", "retrieved_titles": ["A", "B"]}]}
    report_b = {"per_query": [{"query": "q", "retrieved_titles": ["B", "A"]}]}

    agreement = compute_agreement(report_a, report_b)

    assert agreement["per_query"][0]["overlap"] == 2
    assert agreement["per_query"][0]["jaccard"] == 1.0
    assert agreement["mean_jaccard"] == 1.0


def test_compute_agreement_reports_partial_overlap():
    report_a = {"per_query": [{"query": "q", "retrieved_titles": ["A", "B"]}]}
    report_b = {"per_query": [{"query": "q", "retrieved_titles": ["B", "C"]}]}

    agreement = compute_agreement(report_a, report_b)

    assert agreement["per_query"][0]["overlap"] == 1
    assert agreement["per_query"][0]["union"] == 3
    assert agreement["per_query"][0]["jaccard"] == pytest.approx(1 / 3)


def test_compute_agreement_handles_both_backends_returning_nothing():
    report_a = {"per_query": [{"query": "q", "retrieved_titles": []}]}
    report_b = {"per_query": [{"query": "q", "retrieved_titles": []}]}

    agreement = compute_agreement(report_a, report_b)

    assert agreement["per_query"][0]["jaccard"] == 0.0
    assert agreement["mean_jaccard"] == 0.0


def test_compute_agreement_means_across_queries():
    report_a = {"per_query": [
        {"query": "q1", "retrieved_titles": ["A"]},
        {"query": "q2", "retrieved_titles": ["X"]},
    ]}
    report_b = {"per_query": [
        {"query": "q1", "retrieved_titles": ["A"]},
        {"query": "q2", "retrieved_titles": ["Y"]},
    ]}

    agreement = compute_agreement(report_a, report_b)

    assert agreement["mean_jaccard"] == pytest.approx(0.5)


def test_run_eval_reports_recall_per_category():
    golden_queries = [
        {"query": "c1", "category": "conceptual", "expected_doc_titles": ["A"]},
        {"query": "c2", "category": "conceptual", "expected_doc_titles": ["B"]},
        {"query": "k1", "category": "keyword", "expected_doc_titles": ["C"]},
        {"query": "k2", "category": "keyword", "expected_doc_titles": ["MISSING"]},
    ]
    backend_cls = make_fake_backend({"c1": ["A"], "c2": ["B"], "k1": ["C"], "k2": ["Z"]})

    report = run_eval(golden_queries, backend_cls, strategy="semantic", top_k=5)

    assert report["recall_by_category"]["conceptual"] == {"recall": 1.0, "scored": 2}
    assert report["recall_by_category"]["keyword"] == {"recall": 0.5, "scored": 2}
    assert report["recall_at_k"] == 0.75


def test_run_eval_tolerates_queries_without_a_category():
    golden_queries = [
        {"query": "q1", "expected_doc_titles": ["A"]},
        {"query": "q2", "category": "keyword", "expected_doc_titles": ["B"]},
    ]
    backend_cls = make_fake_backend({"q1": ["A"], "q2": ["B"]})

    report = run_eval(golden_queries, backend_cls, strategy="semantic", top_k=5)

    assert report["recall_at_k"] == 1.0
    assert report["recall_by_category"] == {"keyword": {"recall": 1.0, "scored": 1}}


def test_run_eval_excludes_unlabelled_queries_from_category_recall():
    golden_queries = [
        {"query": "k1", "category": "keyword", "expected_doc_titles": ["A"]},
        {"query": "k2", "category": "keyword", "expected_doc_titles": []},
    ]
    backend_cls = make_fake_backend({"k1": ["A"], "k2": ["B"]})

    report = run_eval(golden_queries, backend_cls, strategy="semantic", top_k=5)

    assert report["recall_by_category"]["keyword"] == {"recall": 1.0, "scored": 1}
    assert report["queries_skipped"] == 1


def test_resolve_batch_id_returns_newest_matching_batch():
    from unittest.mock import patch

    import search_docsite.tests.eval.run_eval as m

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (11,)

    with patch.object(m, "get_db_connection", return_value=conn):
        assert m.resolve_batch_id(2500) == 11

    assert cur.execute.call_args[0][1] == (2500,)
    conn.close.assert_called_once()


def test_resolve_batch_id_returns_none_when_no_batch_matches():
    from unittest.mock import patch

    import search_docsite.tests.eval.run_eval as m

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = None

    with patch.object(m, "get_db_connection", return_value=conn):
        assert m.resolve_batch_id(1800) is None

    conn.close.assert_called_once()
