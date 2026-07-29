"""
tests/test_cache.py
====================
Unit tests for ``CacheManager`` -- pure filesystem behavior, no network
requests or collectors involved.
"""

from __future__ import annotations

from src.cache import CacheManager


def test_get_returns_none_for_missing_key(tmp_path) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    assert cache.get("c_399") is None


def test_set_then_get_roundtrips_payload(tmp_path) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    payload = {"club_info": {"id": "c_399"}, "injury_risk_score": 0.25}

    cache.set("c_399", payload)

    assert cache.get("c_399") == payload


def test_set_writes_under_league_season_directory(tmp_path) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    cache.set("c_399", {"foo": "bar"})

    expected_path = tmp_path / "championship" / "2026-2027" / "c_399.json"
    assert expected_path.exists()


def test_is_expired_true_when_key_never_cached(tmp_path) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    assert cache.is_expired("c_399") is True


def test_is_expired_false_within_ttl(tmp_path) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    cache.set("c_399", {"foo": "bar"})

    assert cache.is_expired("c_399", ttl_hours=168) is False


def test_is_expired_true_after_ttl_elapsed(tmp_path, monkeypatch) -> None:
    cache = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    cache.set("c_399", {"foo": "bar"})

    real_time = __import__("time").time

    # Simulate the clock advancing well beyond the TTL window.
    monkeypatch.setattr("src.cache.time.time", lambda: real_time() + 999 * 3600)

    assert cache.is_expired("c_399", ttl_hours=168) is True


def test_different_league_season_pairs_are_isolated(tmp_path) -> None:
    cache_a = CacheManager("championship", "2026-2027", base_dir=str(tmp_path))
    cache_b = CacheManager("league-one", "2026-2027", base_dir=str(tmp_path))

    cache_a.set("c_399", {"league": "a"})

    assert cache_a.get("c_399") == {"league": "a"}
    assert cache_b.get("c_399") is None
