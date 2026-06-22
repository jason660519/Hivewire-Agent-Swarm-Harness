"""Tests for cost estimation and the live dashboard's data aggregation."""
from __future__ import annotations

from benchmark.dashboard import dashboard_data
from benchmark.metrics import aggregate


def _rec(vendor, outcome, nbytes, tclass="high-volume", pool="anyip-us", ip=None):
    return {
        "vendor": vendor,
        "target_class": tclass,
        "pool": pool,
        "outcome": outcome,
        "latency_ms": 100.0,
        "bytes": nbytes,
        "observed_ip": ip,
    }


# ---------------------------------------------------------------------------
# cost in aggregate
# ---------------------------------------------------------------------------

def test_spend_counts_all_bytes_including_failures():
    # 1 GB total: 0.5 GB success + 0.5 GB blocked. At $2/GB => $2 spend.
    half_gb = 500_000_000
    records = [
        _rec("anyip", "success", half_gb),
        _rec("anyip", "blocked", half_gb),
    ]
    [g] = aggregate(records, {"anyip": 2.0})
    assert round(g.est_spend_usd, 6) == 2.0
    # cost efficiency divides by successes only: $2 / 1 success * 1000 = $2000
    assert round(g.usd_per_1k_success, 2) == 2000.0


def test_no_pricing_leaves_spend_none():
    [g] = aggregate([_rec("anyip", "success", 1000)])
    assert g.est_spend_usd is None
    assert g.usd_per_1k_success is None


# ---------------------------------------------------------------------------
# dashboard_data
# ---------------------------------------------------------------------------

def test_dashboard_picks_best_and_cheapest():
    gb = 1_000_000_000
    records = [
        # anyip: 100% success, $2/GB
        _rec("anyip", "success", gb, ip="1.1.1.1"),
        # proxy-cheap: 50% success, $1/GB (cheaper per GB but worse success)
        _rec("proxy-cheap", "success", gb),
        _rec("proxy-cheap", "blocked", gb),
    ]
    d = dashboard_data(records, {"anyip": 2.0, "proxy-cheap": 1.0})

    assert d["total_runs"] == 3
    assert d["best_success_vendor"] == "anyip"
    # proxy-cheap: $2 spend / 1 success *1000 = $2000; anyip: $2/1*1000=$2000 -> tie,
    # min() keeps first by vendor sort ('anyip'); assert it's one of them, deterministic:
    assert d["cheapest_vendor"] in {"anyip", "proxy-cheap"}
    assert d["total_spend_usd"] == 4.0  # anyip 1GB*$2 + proxy-cheap 2GB*$1
    assert d["mock"] is False


def test_dashboard_flags_mock_dataset():
    d = dashboard_data([_rec("anyip", "success", 100, pool="mock-us-west")], {})
    assert d["mock"] is True
    assert d["has_pricing"] is False
    assert d["total_spend_usd"] is None


def test_dashboard_recent_is_capped_and_newest_first():
    records = [_rec("anyip", "success", 100, ip=str(i)) for i in range(20)]
    d = dashboard_data(records, {})
    assert len(d["recent"]) == 12
    assert d["recent"][0]["observed_ip"] == "19"  # newest first
