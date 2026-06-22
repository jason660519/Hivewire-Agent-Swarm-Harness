"""Tests for the HTML report builder — deterministic, no network/filesystem."""
from __future__ import annotations

from benchmark.report import build_html


def _rec(vendor, tclass, outcome, pool="anyip-us", ip=None, ts="2026-06-22T10:00:00+00:00"):
    return {
        "ts": ts,
        "vendor": vendor,
        "target_class": tclass,
        "pool": pool,
        "outcome": outcome,
        "latency_ms": 120.0,
        "bytes": 1024,
        "observed_ip": ip,
    }


def test_build_html_is_self_contained_and_has_data():
    records = [
        _rec("anyip", "high-volume", "success", ip="1.1.1.1"),
        _rec("proxy-cheap", "high-volume", "blocked"),
    ]
    out = build_html(records, generated_at="2026-06-22 10:00 UTC")
    assert out.startswith("<!DOCTYPE html>")
    # no external resources — safe to open/publish offline
    assert "http://" not in out and "https://" not in out
    assert "<svg" in out
    assert "anyip" in out
    assert "proxy-cheap" in out


def test_mock_dataset_shows_banner():
    records = [_rec("anyip", "high-volume", "success", pool="mock-us-west")]
    out = build_html(records, generated_at="x")
    assert "MOCK DATA" in out


def test_real_pool_no_mock_banner():
    records = [_rec("anyip", "high-volume", "success", pool="anyip-residential")]
    out = build_html(records, generated_at="x")
    assert "MOCK DATA" not in out


def test_head_to_head_delta_rendered():
    records = [
        _rec("anyip", "geo", "success"),
        _rec("anyip", "geo", "success"),
        _rec("proxy-cheap", "geo", "success"),
        _rec("proxy-cheap", "geo", "blocked"),
    ]
    out = build_html(records, generated_at="x")
    assert "+50 pp" in out
