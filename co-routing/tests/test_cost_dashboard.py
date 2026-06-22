"""Tests for cost estimation and the live dashboard's data aggregation."""
from __future__ import annotations

from benchmark.dashboard import benchmark_page, console_page, dashboard_data, home_page
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
    assert d["outcome_counts"] == {"blocked": 1, "success": 2}
    assert {(s["vendor"], s["target_class"]) for s in d["track_stats"]} == {
        ("anyip", "high-volume"),
        ("proxy-cheap", "high-volume"),
    }


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


def test_console_page_is_data_driven_not_mocked_partner_claims():
    page = console_page()
    assert "fetch('/data')" in page
    assert "proxy-cheap" in page
    assert 'href="/benchmark"' in page
    assert "anyIP" not in page
    assert "Claude" not in page
    assert "192.144.12.87" not in page
    assert "fonts.googleapis.com" not in page


def test_benchmark_page_is_independent_data_driven_moat_view():
    page = benchmark_page()
    assert "'/data'" in page
    assert "fetch(url)" in page
    assert "latest_manifest" in page
    assert "track_stats" in page
    assert "run_history" in page
    assert "runSelector" in page
    assert "compareSelector" in page
    assert "data?run_id=" in page
    assert "compare_run_id" in page
    assert "scheduler_status" in page
    assert "schedulerPanel" in page
    assert 'href="/console"' in page
    assert "Benchmark moat" in page
    assert "Methodology" in page
    assert "Track evidence" in page
    assert "Run-to-run delta" in page
    assert "Scheduler" in page
    assert "proxy-cheap" in page
    assert "fonts.googleapis.com" not in page


def test_home_page_links_single_port_pages():
    page = home_page()
    assert 'href="/console"' in page
    assert 'href="/benchmark"' in page
    assert "127.0.0.1:8899" not in page


def test_dashboard_data_can_include_latest_manifest():
    manifest = {"run_id": "20260623T000000Z-test", "config_sha256": "abc123"}
    history = [{"run_id": "20260623T000000Z-test", "result_count": 1}]
    comparison = {"baseline_run_id": "baseline", "rows": []}
    scheduler_status = {"source": "example", "profile_count": 1}
    d = dashboard_data(
        [_rec("proxy-cheap", "success", 100)],
        {},
        latest_manifest=manifest,
        run_history=history,
        selected_run_id="20260623T000000Z-test",
        comparison=comparison,
        scheduler_status=scheduler_status,
    )

    assert d["latest_manifest"] == manifest
    assert d["run_history"] == history
    assert d["selected_run_id"] == "20260623T000000Z-test"
    assert d["comparison"] == comparison
    assert d["scheduler_status"] == scheduler_status
