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
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from benchmark.evidence import compare_records, list_run_archives, load_latest_manifest, load_run_archive
from benchmark.metrics import aggregate, load_pricing, load_records
from benchmark.scheduler import collect_scheduler_status

_DIR = Path(__file__).parent


def dashboard_data(
    records: list[dict],
    pricing: dict[str, float],
    *,
    latest_manifest: dict | None = None,
    run_history: list[dict] | None = None,
    selected_run_id: str | None = None,
    comparison: dict | None = None,
    scheduler_status: dict | None = None,
) -> dict:
    """Pure aggregation for the dashboard JSON — testable without a server."""
    stats = aggregate(records, pricing)
    outcome_counts: dict[str, int] = {}
    for r in records:
        outcome = str(r.get("outcome", "unknown"))
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

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
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "track_stats": [asdict(s) for s in stats],
        "latest_manifest": latest_manifest,
        "run_history": run_history or [],
        "selected_run_id": selected_run_id,
        "comparison": comparison,
        "scheduler_status": scheduler_status,
        "recent": list(reversed(records[-12:])),
    }


def console_page() -> str:
    """Data-driven operations console HTML.

    Keep this page honest: it reads the same /data endpoint as the live
    dashboard and must not hard-code partner names, model names, or fake IPs.
    """
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hivewire Console — proxy-cheap baseline</title>
<style>
  :root{
    --bg:#070b12;--panel:#0d1420;--panel2:#111b2a;--line:#223044;
    --text:#dbe7f3;--muted:#7f91a8;--dim:#526174;--cyan:#22d3ee;
    --green:#22c55e;--amber:#f59e0b;--red:#fb7185;--blue:#60a5fa;
  }
  *{box-sizing:border-box} body{margin:0;height:100vh;overflow:hidden;background:var(--bg);
    color:var(--text);font:13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  button,select,textarea{font:inherit}
  .shell{height:100vh;display:grid;grid-template-rows:58px minmax(0,1fr) 118px}
  .top{display:grid;grid-template-columns:250px minmax(360px,1fr) 330px;gap:14px;align-items:center;
    padding:10px 14px;border-bottom:1px solid var(--line);background:#09111d}
  .brand{font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--cyan)}
  .sub{color:var(--muted);font-size:12px;margin-top:2px}
  .nav{display:flex;gap:8px;margin-top:7px}.nav a{color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:7px;padding:3px 7px;font-size:11px}.nav a.active{color:var(--cyan);border-color:#164e63;background:#0b2531}
  .route-strip{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px 12px;
    display:flex;align-items:center;gap:10px;min-width:0}
  .hop{white-space:nowrap}.hop strong{color:var(--text)}.arrow{color:var(--dim)}
  .status-dot{width:8px;height:8px;border-radius:99px;background:var(--green);box-shadow:0 0 10px var(--green)}
  .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .metric{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:7px 9px}
  .label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
  .value{font-weight:750;font-size:16px;font-variant-numeric:tabular-nums;margin-top:1px}
  .workspace{display:grid;grid-template-columns:240px minmax(0,1fr) 350px;min-height:0}
  aside,.inspector{background:var(--panel);border-right:1px solid var(--line);min-height:0;overflow:auto}
  .inspector{border-right:0;border-left:1px solid var(--line)}
  .pane-title{padding:12px 14px;border-bottom:1px solid var(--line);font-size:11px;color:var(--muted);
    text-transform:uppercase;letter-spacing:.08em;font-weight:700}
  .side-section{padding:12px 10px}.side-heading{color:var(--muted);font-size:10px;text-transform:uppercase;margin:8px 4px}
  .vendor-row,.session-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px;
    border-radius:7px;color:var(--text)}
  .vendor-row.active,.session-row.active{background:var(--panel2);outline:1px solid #1f3a52}
  .pill{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:99px;
    padding:2px 7px;color:var(--muted);font-size:11px}
  .main{min-width:0;min-height:0;overflow:auto;background:linear-gradient(180deg,#080d16,#090d14)}
  .toolbar{position:sticky;top:0;z-index:2;display:flex;gap:8px;align-items:center;padding:10px 14px;
    border-bottom:1px solid var(--line);background:rgba(8,13,22,.92);backdrop-filter:blur(8px)}
  .tab{border:1px solid var(--line);background:transparent;color:var(--muted);border-radius:7px;padding:6px 10px;cursor:pointer}
  .tab.active{background:#0b2531;color:var(--cyan);border-color:#164e63}
  .timeline{padding:16px;display:grid;gap:12px}
  .lane{border:1px solid var(--line);border-radius:9px;background:rgba(13,20,32,.72);padding:12px}
  .lane-head{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
  .events{display:flex;gap:10px;overflow:auto;padding-bottom:4px}
  .event{min-width:210px;max-width:250px;text-align:left;border:1px solid var(--line);border-left:3px solid var(--green);
    background:#0b1220;color:var(--text);border-radius:8px;padding:10px;cursor:pointer}
  .event.blocked{border-left-color:var(--amber)}.event.error{border-left-color:var(--red)}
  .event.active{outline:2px solid rgba(34,211,238,.45)}
  .event-type{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
  .event-title{font-weight:700;margin:4px 0}.event-meta{display:flex;justify-content:space-between;color:var(--muted);font-size:11px}
  .route-map{display:none;padding:16px}.route-map.active{display:block}.map-card{border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:16px}
  .node{fill:#0f172a;stroke:#24435a;stroke-width:2}.node-live{stroke:var(--cyan)}.node-text{fill:var(--text);font-size:12px;font-weight:700}.edge{stroke:#31506a;stroke-width:2;stroke-dasharray:7 7}
  .inspector-body{padding:14px}.empty{color:var(--muted);text-align:center;margin-top:40px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.kv{border:1px solid var(--line);border-radius:7px;padding:8px;background:#0a111c}
  pre{white-space:pre-wrap;word-break:break-word;border:1px solid var(--line);background:#060a11;border-radius:8px;padding:10px;color:#bfdbfe;font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  .composer{border-top:1px solid var(--line);background:#09111d;padding:10px 14px;display:grid;grid-template-columns:260px minmax(0,1fr) 160px;gap:12px}
  .modes{display:flex;gap:6px;align-items:flex-start}.mode{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:7px;padding:7px 9px;cursor:pointer}
  .mode.active{color:var(--cyan);border-color:#164e63;background:#0b2531}
  textarea{width:100%;height:78px;resize:none;border:1px solid var(--line);background:#060a11;color:var(--text);border-radius:8px;padding:10px}
  .send{border:1px solid #155e75;background:#0b2531;color:var(--cyan);border-radius:8px;font-weight:750;cursor:pointer}
  @media (max-width:1050px){.top{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}
    .workspace{grid-template-columns:190px minmax(0,1fr)}.inspector{display:none}.composer{grid-template-columns:1fr}}
</style></head><body>
<div class="shell">
  <header class="top">
    <div><div class="brand">Hivewire Console</div><div class="sub" id="subtitle">proxy-cheap baseline · loading data</div><nav class="nav"><a class="active" href="/console">Console</a><a href="/benchmark">Benchmark</a></nav></div>
    <div class="route-strip" aria-label="Current route profile">
      <span class="status-dot"></span><span class="hop"><strong id="modelTier">model tier</strong></span>
      <span class="arrow">--></span><span class="hop"><strong id="egressPool">egress pool</strong></span>
      <span class="arrow">--></span><span class="hop" id="observedIp">observed IP pending</span>
    </div>
    <div class="metrics">
      <div class="metric"><div class="label">Runs</div><div class="value" id="runCount">--</div></div>
      <div class="metric"><div class="label">Spend est.</div><div class="value" id="spend">--</div></div>
      <div class="metric"><div class="label">Success</div><div class="value" id="success">--</div></div>
    </div>
  </header>
  <div class="workspace">
    <aside><div class="pane-title">Sessions & egress</div><div class="side-section">
      <div class="side-heading">Current baseline</div>
      <div class="session-row active"><span>proxy-cheap rotating</span><span class="pill">real</span></div>
      <div class="side-heading">Vendors</div><div id="vendors"></div>
    </div></aside>
    <main class="main">
      <div class="toolbar">
        <button class="tab active" data-view="timeline">Live timeline</button>
        <button class="tab" data-view="route">Egress route</button>
      </div>
      <section id="timeline" class="timeline"></section>
      <section id="route" class="route-map"><div class="map-card">
        <svg viewBox="0 0 760 260" width="100%" height="260" role="img" aria-label="Egress route diagram">
          <line class="edge" x1="150" y1="130" x2="370" y2="130"/><line class="edge" x1="430" y1="130" x2="650" y2="130"/>
          <circle class="node node-live" cx="110" cy="130" r="44"/><circle class="node node-live" cx="400" cy="130" r="52"/><circle class="node" cx="690" cy="130" r="44"/>
          <text class="node-text" x="110" y="125" text-anchor="middle">Agent</text><text class="node-text" x="110" y="143" text-anchor="middle">tool call</text>
          <text class="node-text" x="400" y="125" text-anchor="middle" id="mapPool">proxy-cheap</text><text class="node-text" x="400" y="143" text-anchor="middle" id="mapPolicy">rotating</text>
          <text class="node-text" x="690" y="125" text-anchor="middle">Target</text><text class="node-text" x="690" y="143" text-anchor="middle" id="mapTarget">latest</text>
        </svg>
      </div></section>
    </main>
    <aside class="inspector"><div class="pane-title">Event inspector</div><div class="inspector-body" id="inspector"><div class="empty">Select a timeline event to inspect its real JSONL record.</div></div></aside>
  </div>
  <footer class="composer">
    <div class="modes"><button class="mode active" data-mode="steer">Steer</button><button class="mode" data-mode="follow">Follow-up</button><button class="mode" data-mode="fork">Fork from event</button></div>
    <textarea id="composer" placeholder="Steer the current run. This prototype does not submit yet."></textarea>
    <button class="send" type="button">Preview only</button>
  </footer>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=x=>x==null?'--':Math.round(x*100)+'%';
const usd=x=>x==null?'--':'$'+Number(x).toFixed(4);
let selectedRecord=null;
function inspect(r, btn){
  selectedRecord=r; document.querySelectorAll('.event').forEach(e=>e.classList.remove('active')); if(btn) btn.classList.add('active');
  $('inspector').innerHTML=`<h3>${esc(r.outcome)} · ${esc(r.target_class)}</h3>
    <div class="grid">
      <div class="kv"><div class="label">Vendor</div><div>${esc(r.vendor)}</div></div>
      <div class="kv"><div class="label">Pool</div><div>${esc(r.pool)}</div></div>
      <div class="kv"><div class="label">Latency</div><div>${r.latency_ms!=null?Number(r.latency_ms).toFixed(0)+'ms':'--'}</div></div>
      <div class="kv"><div class="label">Observed IP</div><div>${esc(r.observed_ip||'not recorded')}</div></div>
    </div><div class="label">Raw JSONL record</div><pre>${esc(JSON.stringify(r,null,2))}</pre>`;
}
function render(d){
  const recent=d.recent||[], newest=recent[0]||{}, vendor=(d.vendors||[])[0]||{};
  $('subtitle').textContent=`${d.total_runs} runs · updates every 2s · data from results.jsonl`;
  $('runCount').textContent=d.total_runs??0; $('spend').textContent=d.has_pricing?usd(d.total_spend_usd):'--'; $('success').textContent=pct(vendor.success_rate);
  $('modelTier').textContent='web_fetch'; $('egressPool').textContent=newest.pool||vendor.vendor||'proxy-cheap'; $('observedIp').textContent=newest.observed_ip||'observed IP not recorded';
  $('mapPool').textContent=(newest.vendor||'proxy-cheap').slice(0,18); $('mapPolicy').textContent=newest.session_policy||'rotating'; $('mapTarget').textContent=(newest.target_class||'latest').slice(0,18);
  $('vendors').innerHTML=(d.vendors||[]).map(v=>`<div class="vendor-row ${v.vendor===vendor.vendor?'active':''}"><span>${esc(v.vendor)}</span><span class="pill">${v.runs} runs · ${pct(v.success_rate)}</span></div>`).join('');
  const byLane={};
  recent.forEach(r=>{ const k=r.target_class||'unknown'; (byLane[k] ||= []).push(r); });
  $('timeline').innerHTML=Object.entries(byLane).map(([lane,items])=>`<div class="lane"><div class="lane-head"><span>${esc(lane)}</span><span>${items.length} recent</span></div><div class="events">${
    items.map((r,i)=>`<button class="event ${esc(r.outcome)}" data-lane="${esc(lane)}" data-index="${i}"><div class="event-type">${esc(r.vendor)} · ${esc(r.pool||'pool')}</div><div class="event-title">${esc(r.outcome)} · ${esc(r.status_code??'--')}</div><div class="event-meta"><span>${r.latency_ms!=null?Number(r.latency_ms).toFixed(0)+'ms':'--'}</span><span>${esc(r.session_policy||'')}</span></div></button>`).join('')
  }</div></div>`).join('') || '<div class="empty">No benchmark records yet.</div>';
  document.querySelectorAll('.event').forEach(btn=>btn.addEventListener('click',()=>inspect(byLane[btn.dataset.lane][Number(btn.dataset.index)],btn)));
  if(!selectedRecord && recent[0]) inspect(recent[0], document.querySelector('.event'));
}
async function tick(){ try{ const d=await (await fetch('/data')).json(); render(d); }catch(e){ $('subtitle').textContent='Unable to load /data'; } }
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{ document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); $('timeline').style.display=btn.dataset.view==='timeline'?'grid':'none'; $('route').classList.toggle('active',btn.dataset.view==='route'); }));
document.querySelectorAll('.mode').forEach(btn=>btn.addEventListener('click',()=>{ document.querySelectorAll('.mode').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); const m=btn.dataset.mode; $('composer').placeholder=m==='fork'?'Fork from the selected event and choose a new route profile.':m==='follow'?'Queue a follow-up after the current run finishes.':'Steer the current run. This prototype does not submit yet.'; }));
tick(); setInterval(tick,2000);
</script></body></html>"""


def benchmark_page() -> str:
    """Data-driven benchmark moat page on the same local dashboard port."""
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hivewire Benchmark moat</title>
<style>
  :root{--bg:#070b12;--panel:#0d1420;--panel2:#111b2a;--line:#223044;--text:#dbe7f3;--muted:#7f91a8;--dim:#526174;--cyan:#22d3ee;--green:#22c55e;--amber:#f59e0b;--red:#fb7185;--blue:#60a5fa}
  *{box-sizing:border-box} body{margin:0;min-height:100vh;background:#070b12;color:var(--text);font:13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  .shell{min-height:100vh;display:grid;grid-template-rows:auto 1fr;background:linear-gradient(180deg,#08111d,#070b12 48%,#080d14)}
  header{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:center;padding:16px 18px;border-bottom:1px solid var(--line);background:#09111d}
  .brand{font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--cyan)} .sub{color:var(--muted);font-size:12px;margin-top:3px}
  nav{display:flex;gap:8px} nav a{color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:7px;padding:6px 9px} nav a.active{color:var(--cyan);border-color:#164e63;background:#0b2531}
  .head-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.select-stack{display:grid;gap:4px}.select-label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase} select{background:#0a111c;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;max-width:280px}
  main{padding:18px;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.9fr);gap:16px;align-items:start}.panel{border:1px solid var(--line);border-radius:9px;background:rgba(13,20,32,.82);overflow:hidden}.panel h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0;padding:12px 14px;border-bottom:1px solid var(--line)}
  .hero{padding:18px 18px 16px}.eyebrow{color:var(--cyan);font-size:11px;letter-spacing:.08em;text-transform:uppercase;font-weight:750} h1{font-size:32px;line-height:1.02;margin:8px 0 10px;max-width:720px}.copy{color:#aab8c9;max-width:760px;font-size:14px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:16px}.card{border:1px solid var(--line);border-radius:8px;background:#0a111c;padding:11px 12px}.label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}.value{font-weight:780;font-size:23px;font-variant-numeric:tabular-nums;margin-top:2px}.small{color:var(--muted);font-size:11px;margin-top:3px}
  table{width:100%;border-collapse:collapse;font-size:13px} th,td{padding:9px 11px;border-bottom:1px solid #172235;text-align:left} th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em} td.num{text-align:right;font-variant-numeric:tabular-nums}.badge{display:inline-flex;border:1px solid var(--line);border-radius:99px;padding:2px 7px;color:var(--muted);font-size:11px;margin-left:6px}.badge.win{color:var(--green);border-color:#14532d}.badge.cheap{color:var(--cyan);border-color:#155e75}
  .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.chip{border:1px solid var(--line);border-radius:99px;background:#0a111c;color:#aab8c9;padding:5px 9px;font-size:12px}.chip strong{color:var(--text)}
  .timeline{padding:12px;display:grid;gap:10px}.run{border:1px solid var(--line);border-left:3px solid var(--green);border-radius:8px;background:#0a111c;padding:10px}.run.blocked{border-left-color:var(--amber)}.run.error{border-left-color:var(--red)}.run-top{display:flex;justify-content:space-between;gap:10px;font-weight:700}.run-meta{color:var(--muted);font-size:11px;margin-top:4px}.method{padding:14px;display:grid;gap:10px}.method-row{display:grid;grid-template-columns:94px minmax(0,1fr);gap:10px;border:1px solid var(--line);border-radius:8px;background:#0a111c;padding:10px}.method-key{color:var(--cyan);font-weight:750}.method-copy{color:#aab8c9}.banner{margin:0 18px 16px;border:1px solid #92400e;background:#2b1b08;color:#facc15;border-radius:8px;padding:10px 12px}.empty{color:var(--muted);padding:14px}
  @media (max-width:980px){main{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}header{grid-template-columns:1fr}nav{flex-wrap:wrap}} @media (max-width:560px){.cards{grid-template-columns:1fr}h1{font-size:26px}}
</style></head><body><div class="shell">
<header><div><div class="brand">Hivewire Benchmark moat</div><div class="sub" id="sub">single-port dashboard · loading results.jsonl</div></div><div class="head-actions"><label class="select-stack"><span class="select-label">View</span><select id="runSelector" aria-label="Benchmark run selector"><option value="">Live accumulated dataset</option></select></label><label class="select-stack"><span class="select-label">Compare against</span><select id="compareSelector" aria-label="Benchmark comparison selector"><option value="">No comparison</option></select></label><nav><a href="/console">Console</a><a class="active" href="/benchmark">Benchmark</a></nav></div></header>
<main><section class="panel"><div class="hero"><div class="eyebrow">Benchmark moat</div><h1>Repeatable egress evidence, not a one-off proxy demo.</h1><p class="copy">Hivewire Benchmark should become the proof layer: same tracks, same classifier, same pricing assumptions, and raw JSONL behind every aggregate. Start with proxy-cheap as the control; add any future vendor only when it can run through the identical harness.</p><div id="banner"></div><div class="cards" id="cards"></div><div class="chips" id="outcomes"></div></div><h2>Vendor scorecard</h2><table><thead><tr><th>Vendor</th><th class="num">Runs</th><th class="num">Success</th><th class="num">Est. spend</th><th class="num">$/1k success</th></tr></thead><tbody id="vendors"></tbody></table><h2>Track evidence</h2><table><thead><tr><th>Vendor</th><th>Target class</th><th class="num">Runs</th><th class="num">Success</th><th class="num">Block</th><th class="num">p95 ms</th><th class="num">IPs</th></tr></thead><tbody id="trackStats"></tbody></table><h2>Run-to-run delta</h2><table><thead><tr><th>Vendor</th><th>Target class</th><th class="num">Success</th><th class="num">p95 ms</th><th class="num">$/1k success</th></tr></thead><tbody id="comparisonRows"></tbody></table></section>
<aside class="panel"><h2>Methodology</h2><div class="method"><div class="method-row"><div class="method-key">Control</div><div class="method-copy">proxy-cheap is the baseline until another real provider is configured.</div></div><div class="method-row"><div class="method-key">Tracks</div><div class="method-copy">Target classes separate high-volume, geo-sensitive, and sticky-session behavior.</div></div><div class="method-row"><div class="method-key">Evidence</div><div class="method-copy">Every card is derived from /data, which is derived from results.jsonl.</div></div><div class="method-row"><div class="method-key">Honesty</div><div class="method-copy">Mock runs are flagged so they cannot masquerade as real egress results.</div></div></div><h2>Scheduler</h2><div class="method" id="schedulerPanel"></div><h2>Latest manifest</h2><div class="method" id="manifest"></div><h2>Recent evidence</h2><div class="timeline" id="feed"></div></aside></main></div>
<script>
const pct=x=>x==null?'--':Math.round(x*100)+'%'; const usd=x=>x==null?'--':'$'+Number(x).toFixed(4); const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selectedRunId='', compareRunId='';
const delta=(v,suffix='')=>v==null?'--':`${v>0?'+':''}${Number(v).toFixed(1)}${suffix}`;
async function tick(){let url=selectedRunId?`/data?run_id=${encodeURIComponent(selectedRunId)}`:'/data'; if(compareRunId) url+=`${url.includes('?')?'&':'?'}compare_run_id=${encodeURIComponent(compareRunId)}`;let d;try{d=await (await fetch(url)).json();}catch(e){document.getElementById('sub').textContent='Unable to load /data';return;} const vendors=d.vendors||[], recent=d.recent||[], control=vendors.find(v=>v.vendor==='proxy-cheap')||vendors[0]||{};
document.getElementById('sub').textContent=`${d.total_runs} runs · ${d.selected_run_id?'archived run':'live accumulated dataset'} · updates every 2s`; document.getElementById('banner').innerHTML=d.mock?'<div class="banner">MOCK DATA: some runs used direct mock pools, not real proxy egress.</div>':'';
const latest_manifest=d.latest_manifest||null, track_stats=d.track_stats||[], outcome_counts=d.outcome_counts||{}, run_history=d.run_history||[];
document.getElementById('runSelector').innerHTML='<option value="">Live accumulated dataset</option>'+run_history.map(r=>`<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${r.result_count??0} records${r.mock?' · mock':''}</option>`).join('');
document.getElementById('compareSelector').innerHTML='<option value="">No comparison</option>'+run_history.map(r=>`<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${r.result_count??0} records${r.mock?' · mock':''}</option>`).join('');
document.getElementById('runSelector').value=d.selected_run_id||selectedRunId||'';
document.getElementById('compareSelector').value=compareRunId||'';
document.getElementById('cards').innerHTML=`<div class="card"><div class="label">Total runs</div><div class="value">${d.total_runs??0}</div><div class="small">jsonl records</div></div><div class="card"><div class="label">Control</div><div class="value">${esc(control.vendor||'proxy-cheap')}</div><div class="small">current baseline</div></div><div class="card"><div class="label">Best success</div><div class="value">${esc(d.best_success_vendor||'--')}</div><div class="small">by vendor aggregate</div></div><div class="card"><div class="label">Manifest</div><div class="value">${latest_manifest?esc(latest_manifest.run_id).slice(0,12):'--'}</div><div class="small">latest archived run</div></div>`;
document.getElementById('outcomes').innerHTML=Object.entries(outcome_counts).map(([k,v])=>`<span class="chip"><strong>${esc(k)}</strong> ${v}</span>`).join('')||'<span class="chip">No outcomes yet</span>';
document.getElementById('vendors').innerHTML=vendors.map(v=>`<tr><td>${esc(v.vendor)}${v.vendor===d.best_success_vendor?'<span class="badge win">best</span>':''}${v.vendor===d.cheapest_vendor?'<span class="badge cheap">cheapest</span>':''}</td><td class="num">${v.runs}</td><td class="num">${pct(v.success_rate)}</td><td class="num">${usd(v.est_spend_usd)}</td><td class="num">${usd(v.usd_per_1k_success)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">No benchmark records yet.</td></tr>';
document.getElementById('trackStats').innerHTML=track_stats.map(s=>`<tr><td>${esc(s.vendor)}</td><td>${esc(s.target_class)}</td><td class="num">${s.n}</td><td class="num">${pct(s.success_rate)}</td><td class="num">${pct(s.block_rate)}</td><td class="num">${s.latency_p95_ms==null?'--':Number(s.latency_p95_ms).toFixed(0)}</td><td class="num">${s.unique_ips}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">No track evidence yet.</td></tr>';
document.getElementById('comparisonRows').innerHTML=(d.comparison&&d.comparison.rows||[]).map(r=>`<tr><td>${esc(r.vendor)}</td><td>${esc(r.target_class)}</td><td class="num">${delta(r.success_delta_pp,' pp')}</td><td class="num">${delta(r.p95_delta_ms,' ms')}</td><td class="num">${delta(r.usd_per_1k_success_delta)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Choose an archived run to compare against.</td></tr>';
document.getElementById('manifest').innerHTML=latest_manifest?`<div class="method-row"><div class="method-key">Run</div><div class="method-copy">${esc(latest_manifest.run_id)}</div></div><div class="method-row"><div class="method-key">Config</div><div class="method-copy">${esc(latest_manifest.config_sha256||'missing').slice(0,16)}</div></div><div class="method-row"><div class="method-key">Pricing</div><div class="method-copy">${esc(latest_manifest.pricing_sha256||'missing').slice(0,16)}</div></div><div class="method-row"><div class="method-key">Results</div><div class="method-copy">${latest_manifest.result_count} records · ${latest_manifest.mock?'mock':'real'}</div></div>`:'<div class="empty">Run the benchmark to create benchmark/runs/&lt;run_id&gt;/manifest.json.</div>';
const scheduler_status=d.scheduler_status||{}, profiles=scheduler_status.profiles||[], firstProfile=profiles[0]||null;
document.getElementById('schedulerPanel').innerHTML=`<div class="method-row"><div class="method-key">Profiles</div><div class="method-copy">${scheduler_status.profiles_exists?'local profiles.yaml':scheduler_status.source==='example'?'example only':'missing'} · ${scheduler_status.profile_count||0} profile${(scheduler_status.profile_count||0)===1?'':'s'}</div></div><div class="method-row"><div class="method-key">Latest</div><div class="method-copy">${esc(scheduler_status.latest_run_id||'no archived run yet')}</div></div>${firstProfile?`<div class="method-row"><div class="method-key">${esc(firstProfile.cadence)}</div><div class="method-copy">${esc(firstProfile.name)}<br>${esc(firstProfile.out_log)}</div></div>`:'<div class="method-row"><div class="method-key">Setup</div><div class="method-copy">Copy benchmark/profiles.yaml.example to benchmark/profiles.yaml.</div></div>'}`;
document.getElementById('feed').innerHTML=recent.map(r=>`<div class="run ${esc(r.outcome)}"><div class="run-top"><span>${esc(r.vendor)} · ${esc(r.target_class)}</span><span>${esc(r.outcome)}</span></div><div class="run-meta">${esc(r.pool||'pool')} · ${r.status_code??'--'} · ${r.latency_ms!=null?Number(r.latency_ms).toFixed(0)+'ms':'--'} · ${esc(r.observed_ip||'IP not recorded')}</div></div>`).join('')||'<div class="empty">No recent runs yet.</div>';
}
document.getElementById('runSelector').addEventListener('change',e=>{selectedRunId=e.target.value;tick();});
document.getElementById('compareSelector').addEventListener('change',e=>{compareRunId=e.target.value;tick();});
tick(); setInterval(tick,2000);
</script></body></html>"""


def home_page() -> str:
    """Single-port landing page for local development."""
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hivewire local dashboard</title><style>
  :root{--bg:#070b12;--panel:#0d1420;--line:#223044;--text:#dbe7f3;--muted:#7f91a8;--cyan:#22d3ee}*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(180deg,#08111d,#070b12);color:var(--text);font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:grid;place-items:center;padding:20px}.wrap{width:min(860px,100%)}.brand{color:var(--cyan);letter-spacing:.08em;text-transform:uppercase;font-weight:800}.sub{color:var(--muted);margin:6px 0 20px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.card{border:1px solid var(--line);border-radius:9px;background:rgba(13,20,32,.84);padding:18px;text-decoration:none;color:var(--text)}.card:hover{border-color:#164e63;background:#0b2531}h1{margin:8px 0 0;font-size:34px}.card h2{margin:0 0 8px;font-size:17px}.card p{margin:0;color:#aab8c9}@media(max-width:700px){.grid{grid-template-columns:1fr}h1{font-size:28px}}</style></head><body><main class="wrap"><div class="brand">Hivewire local dashboard</div><h1>One server, two independent pages.</h1><p class="sub">Use the default launcher and stay on one port. Console is for operation; Benchmark is for evidence.</p><section class="grid"><a class="card" href="/console"><h2>Console</h2><p>Operate the live route view, event inspector, and command composer prototype from real results.jsonl data.</p></a><a class="card" href="/benchmark"><h2>Benchmark</h2><p>Review proxy-cheap baseline evidence, methodology, vendor scorecards, and moat-facing metrics.</p></a></section></main></body></html>"""



def _make_handler(jsonl_path: Path, pricing_path: Path, archive_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence per-request stderr spam
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/data":
                query = parse_qs(parsed.query)
                requested_run_id = (query.get("run_id") or [None])[0]
                compare_run_id = (query.get("compare_run_id") or [None])[0]
                run_history = list_run_archives(archive_dir)
                selected_run_id = None
                latest_overall_manifest = load_latest_manifest(archive_dir)
                latest_manifest = latest_overall_manifest
                archive = load_run_archive(archive_dir, requested_run_id) if requested_run_id else None
                if archive is not None:
                    latest_manifest, records = archive
                    selected_run_id = latest_manifest.get("run_id") or requested_run_id
                else:
                    records = load_records(jsonl_path) if jsonl_path.exists() else []
                pricing = load_pricing(pricing_path)
                comparison = None
                compare_archive = load_run_archive(archive_dir, compare_run_id) if compare_run_id else None
                if compare_archive is not None:
                    compare_manifest, compare_records_data = compare_archive
                    comparison = compare_records(
                        records,
                        compare_records_data,
                        pricing,
                        current_run_id=selected_run_id or "live",
                        baseline_run_id=compare_manifest.get("run_id") or compare_run_id,
                    )
                body = json.dumps(
                    dashboard_data(
                        records,
                        pricing,
                        latest_manifest=latest_manifest,
                        run_history=run_history,
                        selected_run_id=selected_run_id,
                        comparison=comparison,
                        scheduler_status=collect_scheduler_status(
                            _DIR / "profiles.yaml",
                            latest_manifest=latest_overall_manifest,
                        ),
                    )
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/console") or self.path.startswith("/mock"):
                body = console_page().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/benchmark"):
                body = benchmark_page().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = home_page().encode()
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

    handler = _make_handler(Path(args.in_path), Path(args.pricing), _DIR / "runs")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"[dashboard] http://127.0.0.1:{args.port}  (reading {args.in_path})")
    print("[dashboard] run the benchmark in another terminal; this page updates live. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped.")


if __name__ == "__main__":
    main()
