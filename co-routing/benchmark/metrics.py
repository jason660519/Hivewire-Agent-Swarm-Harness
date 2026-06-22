"""Benchmark metrics — aggregate the jsonl dataset into a comparison report.

Groups runs by (vendor, target_class) and computes the numbers that actually
decide a proxy: success rate, block rate, latency, and cost-per-successful-fetch
(bytes per success — the proxy is billed per GB, so this is the real $ proxy).
Prints anyIP tracks against the proxy-cheap control side by side.

Usage (from co-routing/):
    uv run python -m benchmark.metrics [--in results.jsonl]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

# Proxies bill per GB on a decimal basis (1 GB = 1e9 bytes), not 2^30.
_BYTES_PER_GB = 1_000_000_000


def load_records(path: Path) -> list[dict]:
    records = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_pricing(path: Path) -> dict[str, float]:
    """{vendor: usd_per_gb}. Empty if the file is absent — cost then shows as —."""
    if not path.exists():
        return {}
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {k: float(v) for k, v in (raw.get("usd_per_gb") or {}).items()}


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile, p in [0,1]. No numpy dependency."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


@dataclass
class GroupStats:
    vendor: str
    target_class: str
    n: int
    success_rate: float
    block_rate: float
    error_rate: float
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    kb_per_success: float | None  # cost proxy: lower is cheaper
    unique_ips: int
    est_spend_usd: float | None  # estimate: all bytes (incl. failures) x $/GB
    usd_per_1k_success: float | None  # cost efficiency: $ per 1000 successful fetches


def aggregate(records: list[dict], pricing: dict[str, float] | None = None) -> list[GroupStats]:
    pricing = pricing or {}
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        groups.setdefault((r["vendor"], r["target_class"]), []).append(r)

    stats: list[GroupStats] = []
    for (vendor, target_class), rs in sorted(groups.items()):
        n = len(rs)
        successes = [r for r in rs if r["outcome"] == "success"]
        blocked = [r for r in rs if r["outcome"] == "blocked"]
        errored = [r for r in rs if r["outcome"] == "error"]
        succ_latencies = [r["latency_ms"] for r in successes if r["latency_ms"] is not None]
        succ_bytes = [r["bytes"] for r in successes if r["bytes"] is not None]
        ips = {r["observed_ip"] for r in rs if r.get("observed_ip")}

        kb_per_success = (
            (sum(succ_bytes) / len(succ_bytes)) / 1024 if succ_bytes else None
        )

        # You pay for bandwidth on EVERY request, including blocked/errored ones
        # — so spend is computed over all bytes, and cost-efficiency divides that
        # by *successful* fetches (you're paying for the failures too).
        rate = pricing.get(vendor)
        if rate is not None:
            all_bytes = sum(r["bytes"] for r in rs if r.get("bytes"))
            est_spend_usd = all_bytes / _BYTES_PER_GB * rate
            usd_per_1k_success = (
                est_spend_usd / len(successes) * 1000 if successes else None
            )
        else:
            est_spend_usd = None
            usd_per_1k_success = None

        stats.append(
            GroupStats(
                vendor=vendor,
                target_class=target_class,
                n=n,
                success_rate=len(successes) / n,
                block_rate=len(blocked) / n,
                error_rate=len(errored) / n,
                latency_p50_ms=percentile(succ_latencies, 0.50),
                latency_p95_ms=percentile(succ_latencies, 0.95),
                kb_per_success=kb_per_success,
                unique_ips=len(ips),
                est_spend_usd=est_spend_usd,
                usd_per_1k_success=usd_per_1k_success,
            )
        )
    return stats


def _fmt_pct(x: float) -> str:
    return f"{x * 100:4.0f}%"


def _fmt_ms(x: float | None) -> str:
    return f"{x:6.0f}" if x is not None else "     —"


def _fmt_kb(x: float | None) -> str:
    return f"{x:7.1f}" if x is not None else "      —"


def _fmt_usd(x: float | None) -> str:
    return f"${x:.4f}" if x is not None else "—"


def render_report(stats: list[GroupStats]) -> str:
    header = (
        f"{'vendor':<12} {'target_class':<14} {'n':>4} "
        f"{'succ':>5} {'block':>6} {'err':>5} "
        f"{'p50ms':>7} {'p95ms':>7} {'KB/succ':>8} {'IPs':>4} "
        f"{'spend':>9} {'$/1k ok':>9}"
    )
    lines = [header, "-" * len(header)]
    for s in stats:
        lines.append(
            f"{s.vendor:<12} {s.target_class:<14} {s.n:>4} "
            f"{_fmt_pct(s.success_rate):>5} {_fmt_pct(s.block_rate):>6} "
            f"{_fmt_pct(s.error_rate):>5} "
            f"{_fmt_ms(s.latency_p50_ms):>7} {_fmt_ms(s.latency_p95_ms):>7} "
            f"{_fmt_kb(s.kb_per_success):>8} {s.unique_ips:>4} "
            f"{_fmt_usd(s.est_spend_usd):>9} {_fmt_usd(s.usd_per_1k_success):>9}"
        )

    # Head-to-head: for each target_class with a proxy-cheap control, show the
    # success-rate delta of each other vendor vs the control.
    by_class: dict[str, list[GroupStats]] = {}
    for s in stats:
        by_class.setdefault(s.target_class, []).append(s)
    h2h = []
    for tclass, group in sorted(by_class.items()):
        control = next((g for g in group if g.vendor == "proxy-cheap"), None)
        if control is None:
            continue
        for g in group:
            if g.vendor == "proxy-cheap":
                continue
            delta = (g.success_rate - control.success_rate) * 100
            h2h.append(
                f"  {tclass:<14} {g.vendor} vs proxy-cheap: "
                f"{delta:+.0f}pp success ({_fmt_pct(g.success_rate)} vs {_fmt_pct(control.success_rate)})"
            )
    if h2h:
        lines += ["", "vs control (proxy-cheap):", *h2h]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hivewire egress benchmark report")
    parser.add_argument(
        "--in",
        dest="in_path",
        default=str(Path(__file__).parent / "results.jsonl"),
        help="jsonl results file (default: benchmark/results.jsonl)",
    )
    args = parser.parse_args()

    path = Path(args.in_path)
    if not path.exists():
        raise SystemExit(f"{path} not found. Run the benchmark first: uv run python -m benchmark.runner")

    records = load_records(path)
    if not records:
        raise SystemExit(f"{path} is empty.")
    pricing = load_pricing(Path(__file__).parent / "pricing.yaml")
    print(f"[metrics] {len(records)} runs from {path}")
    if not pricing:
        print("[metrics] no pricing.yaml — spend shown as — (copy pricing.yaml.example)")
    print()
    print(render_report(aggregate(records, pricing)))


if __name__ == "__main__":
    main()
