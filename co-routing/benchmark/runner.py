"""Benchmark runner — execute egress tracks against targets, emit jsonl.

Each run appends one structured record to a jsonl file, so the dataset
accumulates across days (which IP type / vendor / region succeeds against which
class of target) rather than being a one-shot report.

Runs entirely against the built-in mock pools today (direct connections, so
success rates reflect the target, not a proxy). When real credentials land,
swap the `pool:` names in targets.yaml to real anyIP / proxy-cheap pools and
re-run the identical methodology — that's the whole point of fixing the config
shape now.

Usage (from co-routing/):
    uv run python -m benchmark.runner [targets.yaml] [--out results.jsonl]

Metrics/report: see benchmark/metrics.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from benchmark.evidence import utc_now, write_run_archive
from benchmark.profiles import resolve_profile
from litellm_corouting import egress_async_client
from server import RouteProfile, SessionPolicy, _session_id_for, load_pools, resolve_proxy_url

# HTTP statuses + body markers that signal an anti-bot block rather than a real
# failure. Heuristic and operator-extendable — the point is to separate "the
# proxy got us through" from "the target slammed the door."
_BLOCK_STATUSES = {403, 429, 503}
_BLOCK_MARKERS = (
    "captcha",
    "are you a robot",
    "verify you are human",
    "access denied",
    "request blocked",
    "unusual traffic",
    "cloudflare",
    "attention required",
)
_IPV4 = re.compile(
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)"
)


@dataclass
class RunResult:
    ts: str
    vendor: str
    track: str
    target_class: str
    pool: str
    region: str
    session_policy: str
    session_id: str
    target: str
    run_index: int
    outcome: str  # "success" | "blocked" | "error"
    status_code: int | None
    latency_ms: float | None
    bytes: int | None
    observed_ip: str | None
    error: str | None


def classify_outcome(status_code: int | None, body: str, error: str | None) -> str:
    """success / blocked / error from a response.

    A 200 carrying a captcha/challenge page counts as *blocked*, not success —
    that's exactly the distinction a proxy benchmark exists to measure.
    """
    if error is not None:
        return "error"
    if status_code is None:
        return "error"
    low = body.lower()
    if status_code in _BLOCK_STATUSES or any(m in low for m in _BLOCK_MARKERS):
        return "blocked"
    if 200 <= status_code < 300:
        return "success"
    return "blocked"


def _extract_ip(body: str) -> str | None:
    m = _IPV4.search(body)
    return m.group(0) if m else None


async def fetch_once(
    *,
    pool,
    pool_name: str,
    region: str,
    session_policy: SessionPolicy,
    url: str,
    timeout_s: float,
    ip_echo: bool,
) -> tuple[int | None, str, int | None, str | None, float | None]:
    """One request through the pool's egress. Returns
    (status, body, bytes, error, latency_ms). No SSRF pinning here: benchmark
    targets are operator-chosen and we want the proxy to resolve hostnames
    itself, which is how a real residential proxy behaves."""
    route = RouteProfile(egress_pool=pool_name, region=region, session_policy=session_policy)
    session_id = _session_id_for(pool_name, region, session_policy)
    proxy_url = resolve_proxy_url(pool, route, session_id)
    client = egress_async_client(proxy_url)
    start = time.perf_counter()
    try:
        resp = await client.get(url, follow_redirects=True, timeout=timeout_s)
        latency_ms = (time.perf_counter() - start) * 1000
        body = resp.text
        return resp.status_code, body, len(resp.content), None, latency_ms
    except Exception as exc:  # connection/timeout/proxy failures are real signal
        latency_ms = (time.perf_counter() - start) * 1000
        return None, "", None, f"{type(exc).__name__}: {exc}", latency_ms
    finally:
        await client.aclose()


async def _run_one(sem, *, track, pool, pool_name, target, run_index, timeout_s, ip_echo) -> RunResult:
    async with sem:
        policy = SessionPolicy(track["session_policy"])
        region = track["region"]
        status, body, nbytes, error, latency_ms = await fetch_once(
            pool=pool,
            pool_name=pool_name,
            region=region,
            session_policy=policy,
            url=target,
            timeout_s=timeout_s,
            ip_echo=ip_echo,
        )
        session_id = _session_id_for(pool_name, region, policy)
        return RunResult(
            ts=datetime.now(timezone.utc).isoformat(),
            vendor=track["vendor"],
            track=track["name"],
            target_class=track["target_class"],
            pool=pool_name,
            region=region,
            session_policy=policy.value,
            session_id=session_id,
            target=target,
            run_index=run_index,
            outcome=classify_outcome(status, body, error),
            status_code=status,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            bytes=nbytes,
            observed_ip=_extract_ip(body) if ip_echo else None,
            error=error,
        )


async def run(config: dict, out_path: Path) -> list[RunResult]:
    pools = load_pools()
    runs_per_target = int(config.get("runs_per_target", 3))
    timeout_s = float(config.get("timeout_s", 20))
    sem = asyncio.Semaphore(int(config.get("concurrency", 5)))

    tasks = []
    for track in config["tracks"]:
        pool_name = track["pool"]
        pool = pools.get(pool_name)
        if pool is None:
            raise ValueError(
                f"track {track['name']!r} references unknown pool {pool_name!r}. "
                f"Available: {sorted(pools)}"
            )
        ip_echo = bool(track.get("ip_echo", False))
        for target in track["targets"]:
            for run_index in range(runs_per_target):
                tasks.append(
                    _run_one(
                        sem,
                        track=track,
                        pool=pool,
                        pool_name=pool_name,
                        target=target,
                        run_index=run_index,
                        timeout_s=timeout_s,
                        ip_echo=ip_echo,
                    )
                )

    # Append (don't truncate) — the dataset accumulates across runs. Write each
    # result the moment it completes and flush, so a live dashboard tailing the
    # jsonl sees runs stream in rather than appearing all at once at the end.
    results: list[RunResult] = []
    with open(out_path, "a") as fh:
        for coro in asyncio.as_completed(tasks):
            r = await coro
            fh.write(json.dumps(asdict(r)) + "\n")
            fh.flush()
            results.append(r)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Hivewire egress benchmark runner")
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="track config (default: benchmark/targets.yaml)",
    )
    parser.add_argument(
        "--profile",
        help="named run profile from benchmark/profiles.yaml",
    )
    parser.add_argument(
        "--profiles",
        default=str(Path(__file__).parent / "profiles.yaml"),
        help="profiles file (default: benchmark/profiles.yaml)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="jsonl results file (appended, default: benchmark/results.jsonl)",
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help="directory for per-run evidence packages (default: benchmark/runs)",
    )
    args = parser.parse_args()

    profile = None
    if args.profile:
        profile = resolve_profile(Path(args.profiles), args.profile)
        config_path = profile["config_path"]
        out_path = Path(args.out) if args.out else profile["out_path"]
        archive_dir = Path(args.archive_dir) if args.archive_dir else profile["archive_dir"]
        print(
            f"[benchmark] profile {profile['name']} "
            f"({profile['cadence']}) — {profile.get('description') or 'no description'}"
        )
    else:
        config_path = Path(args.config) if args.config else Path(__file__).parent / "targets.yaml"
        out_path = Path(args.out) if args.out else Path(__file__).parent / "results.jsonl"
        archive_dir = Path(args.archive_dir) if args.archive_dir else Path(__file__).parent / "runs"

    if not config_path.exists():
        raise SystemExit(
            f"{config_path} not found. Copy benchmark/targets.yaml.example to "
            f"benchmark/targets.yaml and edit it."
        )
    with open(config_path) as fh:
        config = yaml.safe_load(fh)

    started_at = utc_now()
    results = asyncio.run(run(config, out_path))
    finished_at = utc_now()
    result_dicts = [asdict(r) for r in results]
    run_dir = write_run_archive(
        config=config,
        config_path=config_path,
        pricing_path=Path(__file__).parent / "pricing.yaml",
        out_path=out_path,
        results=result_dicts,
        archive_dir=archive_dir,
        started_at=started_at,
        finished_at=finished_at,
    )

    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
    print(f"[benchmark] {len(results)} runs -> {out_path}")
    print(f"[benchmark] evidence archive -> {run_dir}")
    print(f"[benchmark] outcomes: {by_outcome}")
    print("[benchmark] aggregate report: uv run python -m benchmark.metrics --in", out_path)


if __name__ == "__main__":
    main()
