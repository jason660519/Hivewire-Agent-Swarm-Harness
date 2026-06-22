"""Tests for the benchmark harness — outcome classification and metric
aggregation. Deterministic, no network (the runner's live fetch is exercised
manually against mock pools, not in CI)."""
from __future__ import annotations

from benchmark.metrics import aggregate, percentile, render_report
from benchmark.runner import _extract_ip, classify_outcome


# ---------------------------------------------------------------------------
# classify_outcome
# ---------------------------------------------------------------------------

def test_2xx_is_success():
    assert classify_outcome(200, "hello world", None) == "success"


def test_block_status_is_blocked():
    assert classify_outcome(403, "", None) == "blocked"
    assert classify_outcome(429, "", None) == "blocked"


def test_200_with_captcha_body_is_blocked():
    # The key distinction a proxy benchmark exists to make.
    assert classify_outcome(200, "Please complete the CAPTCHA to continue", None) == "blocked"


def test_connection_error_is_error():
    assert classify_outcome(None, "", "ConnectError: refused") == "error"


def test_other_4xx_is_blocked():
    assert classify_outcome(404, "not found", None) == "blocked"


# ---------------------------------------------------------------------------
# _extract_ip
# ---------------------------------------------------------------------------

def test_extract_ip_from_json_body():
    assert _extract_ip('{"ip":"203.0.113.42"}') == "203.0.113.42"


def test_extract_ip_none_when_absent():
    assert _extract_ip("no address here") is None


# ---------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------

def test_percentile_basics():
    assert percentile([], 0.5) is None
    assert percentile([10], 0.95) == 10
    assert percentile([10, 20], 0.5) == 15.0


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------

def _rec(vendor, tclass, outcome, latency=100.0, nbytes=1024, ip=None):
    return {
        "vendor": vendor,
        "target_class": tclass,
        "outcome": outcome,
        "latency_ms": latency,
        "bytes": nbytes,
        "observed_ip": ip,
    }


def test_aggregate_rates_and_cost():
    records = [
        _rec("anyip", "high-volume", "success", latency=100, nbytes=2048, ip="1.1.1.1"),
        _rec("anyip", "high-volume", "success", latency=300, nbytes=2048, ip="2.2.2.2"),
        _rec("anyip", "high-volume", "blocked"),
        _rec("anyip", "high-volume", "error"),
    ]
    [g] = aggregate(records)
    assert g.vendor == "anyip"
    assert g.n == 4
    assert g.success_rate == 0.5
    assert g.block_rate == 0.25
    assert g.error_rate == 0.25
    # cost proxy: mean bytes over successes / 1024 = 2048/1024 = 2.0 KB
    assert g.kb_per_success == 2.0
    # latency percentiles computed over successes only
    assert g.latency_p50_ms == 200.0
    assert g.unique_ips == 2


def test_aggregate_groups_by_vendor_and_class():
    records = [
        _rec("anyip", "high-volume", "success"),
        _rec("proxy-cheap", "high-volume", "blocked"),
    ]
    stats = aggregate(records)
    assert {(s.vendor, s.target_class) for s in stats} == {
        ("anyip", "high-volume"),
        ("proxy-cheap", "high-volume"),
    }


def test_render_report_includes_head_to_head_vs_control():
    records = [
        _rec("anyip", "high-volume", "success"),
        _rec("anyip", "high-volume", "success"),
        _rec("proxy-cheap", "high-volume", "success"),
        _rec("proxy-cheap", "high-volume", "blocked"),
    ]
    report = render_report(aggregate(records))
    assert "vs control (proxy-cheap)" in report
    # anyip 100% vs proxy-cheap 50% => +50pp
    assert "+50pp" in report
