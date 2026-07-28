"""Unit tests for DocsiteProcessor's pure text-processing pipeline.

No network/DB: get_docs() (which hits GitHub) is never called directly —
these tests exercise _clean_html/_split_by_headers/_split_oversized_chunks/
_accumulate_chunks/_chunk_adaptor_docs directly against in-memory fixtures.
"""

from embed_docsite.docsite_processor import DocsiteProcessor


def make_processor(**kwargs):
    return DocsiteProcessor(docs_type="general_docs", docs_to_ignore=[], **kwargs)


def test_clean_html_converts_tags():
    p = make_processor()
    result = p._clean_html("<p>Hello</p> <code>x</code> <strong>bold</strong> <em>drop</em>")
    assert result == "Hello\n `x` **bold** drop"


def test_split_by_headers_splits_on_markdown_headers():
    p = make_processor()
    text = "# Title\ncontent one\n## Subtitle\ncontent two"
    sections = p._split_by_headers(text)
    assert sections == ["# Title\ncontent one", "## Subtitle\ncontent two"]


def test_split_oversized_chunks_splits_on_newlines_when_over_target():
    p = make_processor()
    chunk = "a" * 5 + "\n" + "b" * 5 + "\n" + "c" * 5
    result = p._split_oversized_chunks([chunk], target_length=8)
    assert result == ["aaaaa", "bbbbb", "ccccc"]


def test_accumulate_chunks_merges_up_to_target_length():
    p = make_processor()
    splits = ["a" * 5, "b" * 5, "c" * 5]
    result = p._accumulate_chunks(splits, target_length=12, overlap=1, min_length=8)
    assert result == ["aaaaabbbbb", "aaaaabbbbbccccc"]


def test_chunk_adaptor_docs_respects_custom_target_and_min_length():
    p = make_processor(target_length=20, min_length=15, overlap=1)
    json_data = [{"name": "doc-a.md", "docs": "# Header\n" + ("word " * 10).strip()}]

    chunks, metadata_dict = p._chunk_adaptor_docs(json_data)

    assert all(c["name"] == "doc-a.md" for c in chunks)
    assert all(c["docs_type"] == "general_docs" for c in chunks)
    assert "doc-a.md" in metadata_dict


def test_chunk_adaptor_docs_skips_ignored_docs():
    p = DocsiteProcessor(docs_type="general_docs", docs_to_ignore=["skip-me.md"])
    json_data = [{"name": "skip-me.md", "docs": "content"}]

    chunks, metadata_dict = p._chunk_adaptor_docs(json_data)

    assert chunks == []
    assert metadata_dict == {}


def test_constructor_defaults_match_previous_hardcoded_values():
    p = DocsiteProcessor(docs_type="general_docs")
    assert p.target_length == 1000
    assert p.min_length == 700
    assert p.overlap == 1
