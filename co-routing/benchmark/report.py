"""Benchmark report — render the jsonl dataset into one shareable HTML page.

Self-contained: inline CSS + inline SVG, no framework, no server, no external
requests. Open it locally or drop it on GitHub Pages. Shows only aggregate
numbers (rates, latency, cost, IP *counts*) — no individual IPs — so it's safe
to publish.

Honesty guard: if the data came from the built-in mock pools (direct
connections, not real proxy egress), the page says so loudly. A mock report
must never look like a real benchmark.

Usage (from co-routing/):
    uv run python -m benchmark.report [--in results.jsonl] [--out report.html]
"""
from __future__ import annotations

import argparse
import html
from datetime import datetime, timezone
from pathlib import Path

from benchmark.metrics import GroupStats, aggregate, load_records

_VENDOR_COLOR = {"anyip": "#16a34a", "proxy-cheap": "#64748b"}
_FALLBACK_COLORS = ["#2563eb", "#9333ea", "#db2777", "#ea580c"]


def _color_for(vendor: str, seen: dict[str, str]) -> str:
    if vendor in _VENDOR_COLOR:
        return _VENDOR_COLOR[vendor]
    if vendor not in seen:
        seen[vendor] = _FALLBACK_COLORS[len(seen) % len(_FALLBACK_COLORS)]
    return seen[vendor]


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _ms(x: float | None) -> str:
    return f"{x:.0f}" if x is not None else "—"


def _kb(x: float | None) -> str:
    return f"{x:.1f}" if x is not None else "—"


def _success_bar_chart(stats: list[GroupStats]) -> str:
    """Horizontal success-rate bars, one per (vendor, target_class)."""
    if not stats:
        return ""
    row_h, bar_max, label_w, pad = 30, 340, 250, 12
    width = label_w + bar_max + 60
    height = len(stats) * row_h + pad * 2
    seen: dict[str, str] = {}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" font-family="system-ui, sans-serif" font-size="13">'
    ]
    for i, s in enumerate(stats):
        y = pad + i * row_h
        cy = y + row_h / 2
        label = html.escape(f"{s.vendor} · {s.target_class}")
        bar_w = max(1, s.success_rate * bar_max)
        color = _color_for(s.vendor, seen)
        parts.append(
            f'<text x="{label_w - 8}" y="{cy + 4}" text-anchor="end" fill="#334155">{label}</text>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y + 5}" width="{bar_max}" height="{row_h - 12}" '
            f'rx="3" fill="#f1f5f9"/>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y + 5}" width="{bar_w:.1f}" height="{row_h - 12}" '
            f'rx="3" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{label_w + bar_max + 8}" y="{cy + 4}" fill="#0f172a" '
            f'font-weight="600">{_pct(s.success_rate)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _summary_rows(stats: list[GroupStats]) -> str:
    rows = []
    for s in stats:
        rows.append(
            "<tr>"
            f"<td>{html.escape(s.vendor)}</td>"
            f"<td>{html.escape(s.target_class)}</td>"
            f"<td class='num'>{s.n}</td>"
            f"<td class='num good'>{_pct(s.success_rate)}</td>"
            f"<td class='num bad'>{_pct(s.block_rate)}</td>"
            f"<td class='num'>{_pct(s.error_rate)}</td>"
            f"<td class='num'>{_ms(s.latency_p50_ms)}</td>"
            f"<td class='num'>{_ms(s.latency_p95_ms)}</td>"
            f"<td class='num'>{_kb(s.kb_per_success)}</td>"
            f"<td class='num'>{s.unique_ips}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _h2h_rows(stats: list[GroupStats]) -> str:
    by_class: dict[str, list[GroupStats]] = {}
    for s in stats:
        by_class.setdefault(s.target_class, []).append(s)
    out = []
    for tclass, group in sorted(by_class.items()):
        control = next((g for g in group if g.vendor == "proxy-cheap"), None)
        if control is None:
            continue
        for g in group:
            if g.vendor == "proxy-cheap":
                continue
            delta = (g.success_rate - control.success_rate) * 100
            cls = "good" if delta > 0 else ("bad" if delta < 0 else "")
            out.append(
                "<tr>"
                f"<td>{html.escape(tclass)}</td>"
                f"<td>{html.escape(g.vendor)}</td>"
                f"<td class='num {cls}'>{delta:+.0f} pp</td>"
                f"<td class='num'>{_pct(g.success_rate)}</td>"
                f"<td class='num'>{_pct(control.success_rate)}</td>"
                "</tr>"
            )
    if not out:
        return "<tr><td colspan='5' class='muted'>No proxy-cheap control track in this dataset.</td></tr>"
    return "\n".join(out)


def build_html(records: list[dict], *, generated_at: str) -> str:
    stats = aggregate(records)
    n_runs = len(records)
    timestamps = sorted(r["ts"] for r in records if r.get("ts"))
    date_range = f"{timestamps[0][:19]} → {timestamps[-1][:19]}" if timestamps else "—"

    mock_runs = sum(1 for r in records if str(r.get("pool", "")).startswith("mock"))
    banner = ""
    if mock_runs:
        share = "all" if mock_runs == n_runs else f"{mock_runs}/{n_runs}"
        banner = (
            f'<div class="banner">⚠ MOCK DATA — {share} runs used the built-in mock '
            f"pools (direct connections, <strong>not real proxy egress</strong>). "
            f"Success rates reflect the target, not a vendor. Swap in real pools "
            f"before treating these numbers as a benchmark.</div>"
        )

    chart = _success_bar_chart(stats)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hivewire Egress Benchmark</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; color: #0f172a;
         max-width: 920px; margin: 0 auto; padding: 32px 20px 64px; line-height: 1.5; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #64748b; font-size: 14px; margin-bottom: 24px; }}
  .banner {{ background: #fef3c7; border: 1px solid #f59e0b; color: #92400e;
            padding: 12px 14px; border-radius: 8px; font-size: 14px; margin-bottom: 24px; }}
  h2 {{ font-size: 16px; margin: 32px 0 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 7px 10px; text-align: left; border-bottom: 1px solid #f1f5f9; }}
  th {{ color: #64748b; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .good {{ color: #16a34a; font-weight: 600; }}
  .bad {{ color: #dc2626; font-weight: 600; }}
  .muted {{ color: #94a3b8; }}
  .chart {{ margin: 8px 0 8px -4px; }}
  footer {{ margin-top: 40px; color: #94a3b8; font-size: 12px; }}
</style>
</head>
<body>
  <h1>Hivewire Egress Benchmark</h1>
  <div class="sub">{n_runs} runs · {date_range} · generated {html.escape(generated_at)}</div>
  {banner}

  <h2>Success rate by track</h2>
  <div class="chart">{chart}</div>

  <h2>Detail</h2>
  <table>
    <thead><tr>
      <th>Vendor</th><th>Target class</th><th class="num">n</th>
      <th class="num">Success</th><th class="num">Block</th><th class="num">Error</th>
      <th class="num">p50 ms</th><th class="num">p95 ms</th>
      <th class="num">KB/succ</th><th class="num">IPs</th>
    </tr></thead>
    <tbody>
    {_summary_rows(stats)}
    </tbody>
  </table>

  <h2>vs control (proxy-cheap)</h2>
  <table>
    <thead><tr>
      <th>Target class</th><th>Vendor</th><th class="num">Δ success</th>
      <th class="num">Vendor</th><th class="num">Control</th>
    </tr></thead>
    <tbody>
    {_h2h_rows(stats)}
    </tbody>
  </table>

  <footer>
    KB/succ = mean bytes per successful fetch (proxy billed per GB — lower is cheaper).
    A 200 carrying a captcha/challenge counts as blocked, not success.
    Aggregate only; individual IPs are not included.
  </footer>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Hivewire egress benchmark HTML report")
    parser.add_argument(
        "--in",
        dest="in_path",
        default=str(Path(__file__).parent / "results.jsonl"),
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        default=str(Path(__file__).parent / "report.html"),
    )
    args = parser.parse_args()

    path = Path(args.in_path)
    if not path.exists():
        raise SystemExit(f"{path} not found. Run: uv run python -m benchmark.runner")
    records = load_records(path)
    if not records:
        raise SystemExit(f"{path} is empty.")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = Path(args.out_path)
    out.write_text(build_html(records, generated_at=generated_at))
    print(f"[report] {len(records)} runs -> {out}")


if __name__ == "__main__":
    main()
