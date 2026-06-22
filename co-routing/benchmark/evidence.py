"""Benchmark evidence archive.

The live jsonl file is convenient for streaming, but the moat is the auditable
run package: manifest + exact per-run records + summary metrics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from benchmark.metrics import aggregate, load_pricing


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _outcome_counts(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        outcome = str(r.get("outcome", "unknown"))
        counts[outcome] = counts.get(outcome, 0) + 1
    return dict(sorted(counts.items()))


def _run_id(finished_at: str, config_sha256: str | None) -> str:
    stamp = finished_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    stamp = stamp.replace(".000000", "").replace(".", "")
    return f"{stamp[:16]}-{(config_sha256 or 'nohash')[:12]}"


def build_run_manifest(
    *,
    config: dict,
    config_path: Path,
    pricing_path: Path,
    out_path: Path,
    results: list[dict],
    started_at: str,
    finished_at: str,
    run_id: str | None = None,
) -> dict:
    """Build a reproducibility manifest for one benchmark execution."""
    config_sha = _sha256_file(config_path)
    pricing_sha = _sha256_file(pricing_path)
    tracks = config.get("tracks") or []
    vendors = sorted({str(r.get("vendor")) for r in results if r.get("vendor")})
    pools = sorted({str(r.get("pool")) for r in results if r.get("pool")})
    target_classes = sorted({str(r.get("target_class")) for r in results if r.get("target_class")})
    targets = sorted({str(t) for track in tracks for t in (track.get("targets") or [])})

    return {
        "run_id": run_id or _run_id(finished_at, config_sha),
        "started_at": started_at,
        "finished_at": finished_at,
        "config_path": str(config_path),
        "config_sha256": config_sha,
        "pricing_path": str(pricing_path),
        "pricing_sha256": pricing_sha,
        "results_path": str(out_path),
        "runs_per_target": int(config.get("runs_per_target", 0)),
        "concurrency": int(config.get("concurrency", 0)),
        "timeout_s": float(config.get("timeout_s", 0)),
        "track_count": len(tracks),
        "target_count": len(targets),
        "result_count": len(results),
        "vendors": vendors,
        "pools": pools,
        "target_classes": target_classes,
        "outcome_counts": _outcome_counts(results),
        "mock": any(str(r.get("pool", "")).startswith("mock") for r in results),
    }


def build_summary(results: list[dict], pricing_path: Path) -> dict:
    pricing = load_pricing(pricing_path)
    groups = [asdict(s) for s in aggregate(results, pricing)]
    return {
        "result_count": len(results),
        "outcome_counts": _outcome_counts(results),
        "groups": groups,
    }


def compare_records(
    current: list[dict],
    baseline: list[dict],
    pricing: dict[str, float] | None = None,
    *,
    current_run_id: str | None = None,
    baseline_run_id: str | None = None,
) -> dict:
    """Compare aggregate track metrics for two record sets."""
    current_stats = {(s.vendor, s.target_class): s for s in aggregate(current, pricing)}
    baseline_stats = {(s.vendor, s.target_class): s for s in aggregate(baseline, pricing)}
    rows = []
    for key in sorted(set(current_stats) | set(baseline_stats)):
        cur = current_stats.get(key)
        base = baseline_stats.get(key)
        vendor, target_class = key
        cur_success = cur.success_rate if cur else None
        base_success = base.success_rate if base else None
        cur_p95 = cur.latency_p95_ms if cur else None
        base_p95 = base.latency_p95_ms if base else None
        cur_cost = cur.usd_per_1k_success if cur else None
        base_cost = base.usd_per_1k_success if base else None
        rows.append(
            {
                "vendor": vendor,
                "target_class": target_class,
                "current_runs": cur.n if cur else 0,
                "baseline_runs": base.n if base else 0,
                "current_success_rate": cur_success,
                "baseline_success_rate": base_success,
                "success_delta_pp": (
                    (cur_success - base_success) * 100
                    if cur_success is not None and base_success is not None
                    else None
                ),
                "current_p95_ms": cur_p95,
                "baseline_p95_ms": base_p95,
                "p95_delta_ms": (
                    cur_p95 - base_p95 if cur_p95 is not None and base_p95 is not None else None
                ),
                "current_usd_per_1k_success": cur_cost,
                "baseline_usd_per_1k_success": base_cost,
                "usd_per_1k_success_delta": (
                    cur_cost - base_cost if cur_cost is not None and base_cost is not None else None
                ),
            }
        )
    return {
        "current_run_id": current_run_id,
        "baseline_run_id": baseline_run_id,
        "rows": rows,
    }


def write_run_archive(
    *,
    config: dict,
    config_path: Path,
    pricing_path: Path,
    out_path: Path,
    results: list[dict],
    archive_dir: Path,
    started_at: str,
    finished_at: str,
    run_id: str | None = None,
) -> Path:
    """Write one immutable-ish run package under benchmark/runs/<run_id>/."""
    manifest = build_run_manifest(
        config=config,
        config_path=config_path,
        pricing_path=pricing_path,
        out_path=out_path,
        results=results,
        started_at=started_at,
        finished_at=finished_at,
        run_id=run_id,
    )
    run_dir = archive_dir / manifest["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (run_dir / "summary.json").write_text(
        json.dumps(build_summary(results, pricing_path), indent=2, sort_keys=True) + "\n"
    )
    with open(run_dir / "results.jsonl", "w") as fh:
        for r in results:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return run_dir


def load_latest_manifest(archive_dir: Path) -> dict | None:
    manifests = sorted(archive_dir.glob("*/manifest.json"), key=lambda p: p.parent.name)
    if not manifests:
        return None
    with open(manifests[-1]) as fh:
        return json.load(fh)


def list_run_archives(archive_dir: Path) -> list[dict]:
    """Return archived run manifests newest-first."""
    runs = []
    for manifest_path in sorted(archive_dir.glob("*/manifest.json"), key=lambda p: p.parent.name, reverse=True):
        with open(manifest_path) as fh:
            manifest = json.load(fh)
        runs.append(
            {
                "run_id": manifest.get("run_id") or manifest_path.parent.name,
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "result_count": manifest.get("result_count", 0),
                "outcome_counts": manifest.get("outcome_counts", {}),
                "vendors": manifest.get("vendors", []),
                "target_classes": manifest.get("target_classes", []),
                "mock": bool(manifest.get("mock", False)),
            }
        )
    return runs


def load_run_archive(archive_dir: Path, run_id: str) -> tuple[dict, list[dict]] | None:
    """Load one archived run by id. Returns None for missing/unsafe ids."""
    if not run_id or Path(run_id).name != run_id or "/" in run_id or "\\" in run_id:
        return None
    run_dir = archive_dir / run_id
    manifest_path = run_dir / "manifest.json"
    results_path = run_dir / "results.jsonl"
    if not manifest_path.exists() or not results_path.exists():
        return None
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    records = []
    with open(results_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return manifest, records


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
