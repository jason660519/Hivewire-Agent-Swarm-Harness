"""Live benchmark dashboard — watch runs stream in, see spend and which vendor wins.

Built for the operator (you), not for end-users: a single auto-refreshing local
page that reads the growing results.jsonl and shows running totals. No
framework, no build step — Python stdlib http.server only.

Two terminals:
    # terminal A — start the dashboard
    uv run python -m benchmark.dashboard
    # terminal B — run the benchmark; the page updates live as results land
    uv run python -m benchmark.runner

Then open http://127.0.0.1:8799 . Spend is an ESTIMATE (see pricing.yaml.example)
— good for comparing vendors, not for accounting.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from benchmark.metrics import aggregate, load_pricing, load_records

_DIR = Path(__file__).parent


def dashboard_data(records: list[dict], pricing: dict[str, float]) -> dict:
    """Pure aggregation for the dashboard JSON — testable without a server."""
    stats = aggregate(records, pricing)

    # Roll groups up to one row per vendor (the operator thinks "which vendor",
    # the per-target-class detail lives in the report).
    by_vendor: dict[str, dict] = {}
    for r in records:
        v = by_vendor.setdefault(
            r["vendor"], {"vendor": r["vendor"], "runs": 0, "success": 0, "bytes": 0}
        )
        v["runs"] += 1
        v["success"] += 1 if r["outcome"] == "success" else 0
        v["bytes"] += r.get("bytes") or 0

    vendors = []
    for v in by_vendor.values():
        rate = pricing.get(v["vendor"])
        spend = (v["bytes"] / 1_000_000_000 * rate) if rate is not None else None
        succ_rate = v["success"] / v["runs"] if v["runs"] else 0.0
        per_1k = (spend / v["success"] * 1000) if (spend is not None and v["success"]) else None
        vendors.append(
            {
                "vendor": v["vendor"],
                "runs": v["runs"],
                "success_rate": succ_rate,
                "est_spend_usd": spend,
                "usd_per_1k_success": per_1k,
            }
        )
    vendors.sort(key=lambda x: x["vendor"])

    real = [x for x in vendors if x["vendor"] != "mock"]
    best_success = max(real, key=lambda x: x["success_rate"], default=None)
    cheapest = min(
        (x for x in real if x["usd_per_1k_success"] is not None),
        key=lambda x: x["usd_per_1k_success"],
        default=None,
    )

    total_spend = sum(x["est_spend_usd"] for x in vendors if x["est_spend_usd"] is not None)
    has_pricing = any(x["est_spend_usd"] is not None for x in vendors)

    return {
        "total_runs": len(records),
        "total_spend_usd": total_spend if has_pricing else None,
        "has_pricing": has_pricing,
        "mock": any(str(r.get("pool", "")).startswith("mock") for r in records),
        "vendors": vendors,
        "best_success_vendor": best_success["vendor"] if best_success else None,
        "cheapest_vendor": cheapest["vendor"] if cheapest else None,
        "recent": list(reversed(records[-12:])),
    }


_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hivewire Benchmark — Live</title>
<style>
  body{font-family:system-ui,sans-serif;color:#0f172a;max-width:900px;margin:0 auto;padding:28px 20px;background:#f8fafc}
  h1{font-size:20px;margin:0 0 2px}
  .sub{color:#64748b;font-size:13px;margin-bottom:20px}
  .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;min-width:150px;flex:1}
  .card .k{color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
  .card .v{font-size:24px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
  table{width:100%;border-collapse:collapse;font-size:14px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}
  th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #f1f5f9}
  th{color:#64748b;font-weight:600;font-size:11px;text-transform:uppercase}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  .badge{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:99px;margin-left:6px}
  .win{background:#dcfce7;color:#166534}.cheap{background:#dbeafe;color:#1e40af}
  .banner{background:#fef3c7;border:1px solid #f59e0b;color:#92400e;padding:9px 12px;border-radius:8px;font-size:13px;margin-bottom:16px}
  .good{color:#16a34a}.bad{color:#dc2626}.muted{color:#94a3b8}
  h2{font-size:14px;margin:24px 0 8px;color:#334155}
  .feed{font-size:13px;font-variant-numeric:tabular-nums}
  .dot{display:inline-block;width:8px;height:8px;border-radius:99px;margin-right:7px;vertical-align:middle}
</style></head><body>
<h1>Hivewire Benchmark <span class="muted" style="font-weight:400">· live</span></h1>
<div class="sub" id="sub">connecting…</div>
<div id="banner"></div>
<div class="cards" id="cards"></div>
<h2>Vendors</h2>
<table><thead><tr><th>Vendor</th><th class="num">Runs</th><th class="num">Success</th>
<th class="num">Est. spend</th><th class="num">$/1k success</th></tr></thead>
<tbody id="vendors"></tbody></table>
<h2>Recent runs</h2>
<div class="feed" id="feed"></div>
<script>
const pct=x=>(x*100).toFixed(0)+'%';
const usd=x=>x==null?'—':'$'+x.toFixed(4);
const oc={success:'#16a34a',blocked:'#f59e0b',error:'#dc2626'};
async function tick(){
  let d; try{ d=await (await fetch('/data')).json(); }catch(e){ return; }
  document.getElementById('sub').textContent=`${d.total_runs} runs · updates every 2s`;
  document.getElementById('banner').innerHTML = d.mock
    ? '<div class="banner">⚠ MOCK DATA — direct connections, not real proxy egress. Spend/success reflect the target, not a vendor.</div>' : '';
  document.getElementById('cards').innerHTML =
    `<div class="card"><div class="k">Total runs</div><div class="v">${d.total_runs}</div></div>`+
    `<div class="card"><div class="k">Est. spend</div><div class="v">${d.has_pricing?usd(d.total_spend_usd):'—'}</div></div>`+
    `<div class="card"><div class="k">Best success</div><div class="v">${d.best_success_vendor||'—'}</div></div>`+
    `<div class="card"><div class="k">Cheapest / success</div><div class="v">${d.cheapest_vendor||'—'}</div></div>`;
  document.getElementById('vendors').innerHTML = d.vendors.map(v=>{
    const win = v.vendor===d.best_success_vendor?'<span class="badge win">best</span>':'';
    const ch = v.vendor===d.cheapest_vendor?'<span class="badge cheap">cheapest</span>':'';
    return `<tr><td>${v.vendor}${win}${ch}</td><td class="num">${v.runs}</td>`+
      `<td class="num">${pct(v.success_rate)}</td><td class="num">${usd(v.est_spend_usd)}</td>`+
      `<td class="num">${usd(v.usd_per_1k_success)}</td></tr>`;
  }).join('');
  document.getElementById('feed').innerHTML = d.recent.map(r=>
    `<div><span class="dot" style="background:${oc[r.outcome]||'#94a3b8'}"></span>`+
    `${r.vendor} · ${r.target_class} · ${r.outcome} · ${r.status_code??'—'} · `+
    `${r.latency_ms!=null?r.latency_ms.toFixed(0)+'ms':'—'} · ${r.observed_ip||''}</div>`).join('');
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


def _make_handler(jsonl_path: Path, pricing_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence per-request stderr spam
            pass

        def do_GET(self):
            if self.path.startswith("/data"):
                records = load_records(jsonl_path) if jsonl_path.exists() else []
                pricing = load_pricing(pricing_path)
                body = json.dumps(dashboard_data(records, pricing)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = _PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Hivewire live benchmark dashboard")
    parser.add_argument("--in", dest="in_path", default=str(_DIR / "results.jsonl"))
    parser.add_argument("--pricing", default=str(_DIR / "pricing.yaml"))
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()

    handler = _make_handler(Path(args.in_path), Path(args.pricing))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"[dashboard] http://127.0.0.1:{args.port}  (reading {args.in_path})")
    print("[dashboard] run the benchmark in another terminal; this page updates live. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped.")


if __name__ == "__main__":
    main()
