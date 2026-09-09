"""Tests for the adaptor cache fallback behavior.

A per-adaptor GitHub fetch failure (e.g. rate limiting) must never poison the
cache: the adaptor keeps its previous cached entry, and a None is never stored.
"""
import json
import os

import pytest

import latest_adaptors.latest_adaptors as la

LISTING = [
    {"name": "alpha", "type": "dir"},
    {"name": "beta", "type": "dir"},
    {"name": "gamma", "type": "dir"},
]

OLD_CACHE = {
    "alpha": {"description": "old alpha", "label": "a", "version": "1.0.0"},
    "beta": {"description": "old beta", "label": "b", "version": "2.0.0"},
    "poisoned": None,  # legacy entry written by the pre-fix code
}


class FakeResponse:
    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail

    def raise_for_status(self):
        if self.fail:
            raise Exception("429 Client Error: Too Many Requests")

    def json(self):
        return self.payload


def fake_get(url, **kwargs):
    """Listing succeeds; the per-package fetch for 'beta' is rate-limited."""
    if "api.github.com" in url:
        return FakeResponse(LISTING)
    if "/beta/" in url:
        return FakeResponse(fail=True)
    name = url.split("/packages/")[1].split("/")[0]
    return FakeResponse({"description": f"desc {name}", "label": name, "version": "9.9.9"})


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "adaptors_cache.json"
    monkeypatch.setattr(la, "ADAPTORS_CACHE_PATH", str(path))
    return path


def write_stale_cache(path, data):
    path.write_text(json.dumps(data))
    # Backdate the mtime so the cache is treated as stale
    os.utime(path, (0, 0))


def test_failed_adaptor_keeps_previous_entry(cache_path, monkeypatch):
    write_stale_cache(cache_path, OLD_CACHE)
    monkeypatch.setattr(la.requests, "get", fake_get)

    result = la.get_latest_adaptors_cached()

    assert result["alpha"]["version"] == "9.9.9"
    assert result["gamma"]["version"] == "9.9.9"
    # beta's fetch failed, so its previous entry survives unchanged
    assert result["beta"] == OLD_CACHE["beta"]
    assert None not in result.values()
    # The written cache matches what was returned
    assert json.loads(cache_path.read_text()) == result


def test_cold_start_failure_omits_adaptor(cache_path, monkeypatch):
    monkeypatch.setattr(la.requests, "get", fake_get)

    result = la.get_latest_adaptors_cached()

    assert "beta" not in result
    assert None not in result.values()
    assert result["alpha"]["version"] == "9.9.9"


def test_total_failure_serves_stale_cache(cache_path, monkeypatch):
    write_stale_cache(cache_path, OLD_CACHE)
    monkeypatch.setattr(la.requests, "get", lambda url, **_: FakeResponse(fail=True))

    result = la.get_latest_adaptors_cached()

    assert result == {"alpha": OLD_CACHE["alpha"], "beta": OLD_CACHE["beta"]}
    # A failed refresh must not overwrite the cache file
    assert json.loads(cache_path.read_text()) == OLD_CACHE


def test_poisoned_entries_dropped_on_load(cache_path):
    cache_path.write_text(json.dumps(OLD_CACHE))

    result = la.get_latest_adaptors_cached()

    assert "poisoned" not in result
    assert result["alpha"] == OLD_CACHE["alpha"]
