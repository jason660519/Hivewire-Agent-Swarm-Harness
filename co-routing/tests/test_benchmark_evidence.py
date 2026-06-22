"""Tests for benchmark evidence manifests and archived runs."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from benchmark.evidence import (
    build_run_manifest,
    compare_records,
    list_run_archives,
    load_run_archive,
    write_run_archive,
)


def _record(vendor="proxy-cheap", outcome="success", pool="proxycheap-rotating"):
    return {
        "ts": "2026-06-23T00:00:00+00:00",
        "vendor": vendor,
        "track": "high-volume-control",
        "target_class": "high-volume",
        "pool": pool,
        "region": "us",
        "session_policy": "rotating",
        "session_id": "s1",
        "target": "https://httpbin.org/ip",
        "run_index": 0,
        "outcome": outcome,
        "status_code": 200,
        "latency_ms": 120.0,
        "bytes": 512,
        "observed_ip": "203.0.113.10",
        "error": None,
    }


def test_build_run_manifest_fingerprints_inputs_and_counts_results(tmp_path: Path):
    config_path = tmp_path / "targets.yaml"
    pricing_path = tmp_path / "pricing.yaml"
    out_path = tmp_path / "results.jsonl"
    config = {
        "runs_per_target": 2,
        "tracks": [
            {
                "name": "high-volume-control",
                "vendor": "proxy-cheap",
                "pool": "proxycheap-rotating",
                "region": "us",
                "session_policy": "rotating",
                "target_class": "high-volume",
                "targets": ["https://httpbin.org/ip"],
            }
        ],
    }
    config_path.write_text(yaml.safe_dump(config))
    pricing_path.write_text("usd_per_gb:\n  proxy-cheap: 1.0\n")

    manifest = build_run_manifest(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=[_record(), _record(outcome="blocked")],
        started_at="2026-06-23T00:00:00Z",
        finished_at="2026-06-23T00:01:00Z",
        run_id="20260623T000000Z-test",
    )

    assert manifest["run_id"] == "20260623T000000Z-test"
    assert manifest["config_sha256"]
    assert manifest["pricing_sha256"]
    assert manifest["result_count"] == 2
    assert manifest["outcome_counts"] == {"blocked": 1, "success": 1}
    assert manifest["vendors"] == ["proxy-cheap"]
    assert manifest["pools"] == ["proxycheap-rotating"]
    assert manifest["mock"] is False


def test_write_run_archive_writes_manifest_results_and_summary(tmp_path: Path):
    config_path = tmp_path / "targets.yaml"
    pricing_path = tmp_path / "pricing.yaml"
    out_path = tmp_path / "results.jsonl"
    archive_dir = tmp_path / "runs"
    config = {"runs_per_target": 1, "tracks": []}
    config_path.write_text(yaml.safe_dump(config))
    pricing_path.write_text("usd_per_gb:\n  proxy-cheap: 2.0\n")

    run_dir = write_run_archive(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=[_record()],
        archive_dir=archive_dir,
        started_at="2026-06-23T00:00:00Z",
        finished_at="2026-06-23T00:01:00Z",
        run_id="20260623T000000Z-test",
    )

    assert run_dir == archive_dir / "20260623T000000Z-test"
    assert json.loads((run_dir / "manifest.json").read_text())["result_count"] == 1
    assert len((run_dir / "results.jsonl").read_text().strip().splitlines()) == 1
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["outcome_counts"] == {"success": 1}
    assert summary["groups"][0]["vendor"] == "proxy-cheap"


def test_list_run_archives_returns_newest_first(tmp_path: Path):
    config_path = tmp_path / "targets.yaml"
    pricing_path = tmp_path / "pricing.yaml"
    out_path = tmp_path / "results.jsonl"
    archive_dir = tmp_path / "runs"
    config = {"runs_per_target": 1, "tracks": []}
    config_path.write_text(yaml.safe_dump(config))
    pricing_path.write_text("usd_per_gb:\n  proxy-cheap: 2.0\n")

    write_run_archive(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=[_record()],
        archive_dir=archive_dir,
        started_at="2026-06-23T00:00:00Z",
        finished_at="2026-06-23T00:01:00Z",
        run_id="20260623T000000Z-a",
    )
    write_run_archive(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=[_record(outcome="blocked")],
        archive_dir=archive_dir,
        started_at="2026-06-24T00:00:00Z",
        finished_at="2026-06-24T00:01:00Z",
        run_id="20260624T000000Z-b",
    )

    runs = list_run_archives(archive_dir)

    assert [r["run_id"] for r in runs] == ["20260624T000000Z-b", "20260623T000000Z-a"]
    assert runs[0]["result_count"] == 1
    assert runs[0]["outcome_counts"] == {"blocked": 1}


def test_load_run_archive_rejects_path_traversal_and_loads_records(tmp_path: Path):
    config_path = tmp_path / "targets.yaml"
    pricing_path = tmp_path / "pricing.yaml"
    out_path = tmp_path / "results.jsonl"
    archive_dir = tmp_path / "runs"
    config = {"runs_per_target": 1, "tracks": []}
    config_path.write_text(yaml.safe_dump(config))
    pricing_path.write_text("usd_per_gb:\n  proxy-cheap: 2.0\n")
    write_run_archive(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=[_record()],
        archive_dir=archive_dir,
        started_at="2026-06-23T00:00:00Z",
        finished_at="2026-06-23T00:01:00Z",
        run_id="20260623T000000Z-test",
    )

    loaded = load_run_archive(archive_dir, "20260623T000000Z-test")

    assert loaded is not None
    manifest, records = loaded
    assert manifest["run_id"] == "20260623T000000Z-test"
    assert records[0]["vendor"] == "proxy-cheap"
    assert load_run_archive(archive_dir, "../secret") is None


def test_compare_records_reports_track_deltas():
    current = [
        _record(outcome="success"),
        _record(outcome="success"),
        _record(outcome="blocked"),
    ]
    baseline = [
        _record(outcome="success"),
        _record(outcome="blocked"),
        _record(outcome="blocked"),
    ]

    comparison = compare_records(
        current,
        baseline,
        {"proxy-cheap": 2.0},
        current_run_id="current-run",
        baseline_run_id="baseline-run",
    )

    assert comparison["current_run_id"] == "current-run"
    assert comparison["baseline_run_id"] == "baseline-run"
    [row] = comparison["rows"]
    assert row["vendor"] == "proxy-cheap"
    assert row["target_class"] == "high-volume"
    assert round(row["success_delta_pp"], 1) == 33.3
    assert row["current_success_rate"] == 2 / 3
    assert row["baseline_success_rate"] == 1 / 3
