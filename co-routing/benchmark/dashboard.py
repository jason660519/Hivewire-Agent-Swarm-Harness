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
    compare_records: list[dict] | None = None,
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
        "compare_records": compare_records or [],
        "scheduler_status": scheduler_status,
        "recent": list(reversed(records[-12:])),
    }


def console_page() -> str:
    """Data-driven operations console HTML.

    Keep this page honest: it reads the same /data endpoint as the live
    dashboard and must not hard-code partner names, model names, or fake IPs.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hivewire Operations Console</title>
  <!-- Local Typography Fallback -->
  
  <style>
    :root {
      --bg-dark: #070a13;
      --bg-panel: rgba(13, 20, 32, 0.7);
      --bg-active: rgba(31, 41, 55, 0.85);
      --border-color: rgba(255, 255, 255, 0.08);
      --border-active: rgba(255, 255, 255, 0.15);
      --text-main: #e2e8f0;
      --text-muted: #64748b;
      --text-dim: #94a3b8;
      
      --color-emerald: #10b981;
      --color-emerald-bg: rgba(16, 185, 129, 0.1);
      --color-amber: #f59e0b;
      --color-amber-bg: rgba(245, 158, 11, 0.1);
      --color-rose: #f43f5e;
      --color-rose-bg: rgba(244, 63, 94, 0.1);
      --color-cyan: #06b6d4;
      --color-cyan-bg: rgba(6, 182, 212, 0.1);
      --color-indigo: #6366f1;
      --color-indigo-bg: rgba(99, 102, 241, 0.1);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: 'Inter', system-ui, sans-serif;
      background-color: var(--bg-dark);
      background-image: radial-gradient(circle at top right, rgba(99, 102, 241, 0.05), transparent 400px),
                        radial-gradient(circle at bottom left, rgba(6, 182, 212, 0.03), transparent 300px);
      color: var(--text-main);
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }

    /* Scrollbar Styling */
    ::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    ::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.1);
    }
    ::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: rgba(255, 255, 255, 0.15);
    }

    /* Top Bar */
    .top-bar {
      height: 56px;
      border-bottom: 1px solid var(--border-color);
      display: grid;
      grid-template-columns: 240px 1fr auto;
      align-items: center;
      padding: 0 16px;
      background: var(--bg-panel);
      backdrop-filter: blur(12px);
      z-index: 10;
    }

    .brand-section {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo {
      font-weight: 700;
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: linear-gradient(135deg, #06b6d4, #6366f1);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .logo::before {
      content: '';
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #06b6d4;
      border-radius: 50%;
      box-shadow: 0 0 8px #06b6d4;
    }

    .nav-links {
      display: flex;
      gap: 6px;
      margin-left: 8px;
    }

    .nav-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 4px;
      border: 1px solid transparent;
      transition: all 0.2s;
    }

    .nav-links a.active {
      color: var(--color-cyan);
      background: rgba(6, 182, 212, 0.08);
      border-color: rgba(6, 182, 212, 0.15);
    }

    /* Egress Circuit Header (Option A) */
    .egress-circuit {
      justify-self: center;
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      font-family: 'JetBrains Mono', monospace;
      background: rgba(0, 0, 0, 0.25);
      padding: 6px 14px;
      border-radius: 20px;
      border: 1px solid var(--border-color);
      max-width: 95%;
      overflow: hidden;
    }

    .circuit-node {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 1px 4px;
    }
    
    .circuit-node.model { color: var(--color-cyan); }
    .circuit-node.egress { color: var(--color-indigo); }
    .circuit-node.ip { color: var(--text-main); font-weight: 500; }
    
    .circuit-arrow {
      color: var(--text-muted);
      font-size: 10px;
    }

    .status-dot {
      width: 6px;
      height: 6px;
      background-color: var(--color-emerald);
      border-radius: 50%;
      box-shadow: 0 0 6px var(--color-emerald);
    }

    .global-metrics {
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 12px;
    }

    .metric-item {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
    }

    .metric-label {
      font-size: 9px;
      text-transform: uppercase;
      color: var(--text-muted);
      letter-spacing: 0.05em;
    }

    .metric-value {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 600;
      color: var(--text-main);
    }

    /* Layout Wrapper */
    .workspace {
      flex: 1;
      display: grid;
      grid-template-columns: 240px 1fr 340px;
      overflow: hidden;
      position: relative;
    }

    /* Sidebar: Session Tree */
    aside {
      border-right: 1px solid var(--border-color);
      background: var(--bg-panel);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .sidebar-header {
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 12px;
      border-bottom: 1px solid var(--border-color);
    }

    .sidebar-title {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      font-weight: 700;
    }

    .sidebar-content {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
    }

    .list-heading {
      font-size: 9px;
      color: var(--text-muted);
      margin: 12px 4px 6px;
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: 0.05em;
    }

    .selector-block {
      padding: 6px 4px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      margin-bottom: 8px;
    }

    .selector-block label {
      font-size: 10px;
      color: var(--text-muted);
      text-transform: uppercase;
    }

    select {
      width: 100%;
      background: rgba(0,0,0,0.3);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      color: var(--text-main);
      padding: 5px 8px;
      font-size: 11px;
      outline: none;
      font-family: 'JetBrains Mono', monospace;
    }
    select:focus {
      border-color: var(--color-cyan);
    }

    .vendor-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 8px;
      border-radius: 6px;
      font-size: 12px;
      color: var(--text-dim);
      margin-bottom: 2px;
      border: 1px solid transparent;
    }

    .vendor-row.active {
      background: var(--bg-active);
      color: var(--text-main);
      border-color: rgba(255,255,255,0.03);
    }

    .pill {
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      background: rgba(255, 255, 255, 0.04);
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--text-muted);
    }

    /* Main Area */
    .main-viewport {
      display: flex;
      flex-direction: column;
      background: #090c14;
      overflow: hidden;
    }

    .view-toolbar {
      height: 40px;
      border-bottom: 1px solid var(--border-color);
      background: rgba(13, 20, 32, 0.4);
      display: flex;
      align-items: center;
      padding: 0 12px;
      gap: 4px;
    }

    .tab-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 12px;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 500;
      transition: all 0.2s;
    }

    .tab-btn:hover {
      color: var(--text-main);
      background: rgba(255, 255, 255, 0.03);
    }

    .tab-btn.active {
      color: var(--color-cyan);
      background: rgba(6, 182, 212, 0.08);
      border: 1px solid rgba(6, 182, 212, 0.15);
    }

    .view-panel {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: none;
    }

    .view-panel.active {
      display: flex;
      flex-direction: column;
    }

    /* Option B: Chronological Swimlanes */
    .timeline-container {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .lane {
      background: rgba(255, 255, 255, 0.015);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 12px;
    }

    .lane-head {
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 8px;
    }

    .lane-events {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding-bottom: 4px;
    }

    /* Event Card Node */
    .event-card {
      background: rgba(13, 20, 32, 0.85);
      border: 1px solid var(--border-color);
      border-left: 3px solid var(--color-emerald);
      border-radius: 6px;
      padding: 8px 12px;
      min-width: 190px;
      max-width: 240px;
      cursor: pointer;
      transition: all 0.2s;
      font-size: 11px;
      flex-shrink: 0;
      text-align: left;
    }

    .event-card.success { border-left-color: var(--color-emerald); }
    .event-card.blocked { border-left-color: var(--color-amber); }
    .event-card.error { border-left-color: var(--color-rose); }

    .event-card:hover {
      border-color: var(--border-active);
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }

    .event-card.active {
      border-color: var(--color-cyan);
      box-shadow: 0 0 8px rgba(6, 182, 212, 0.25);
    }

    .event-type {
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: 3px;
    }

    .event-title {
      font-weight: 600;
      color: var(--text-main);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 4px;
    }

    .event-meta {
      display: flex;
      justify-content: space-between;
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      color: var(--text-muted);
    }

    /* Option B: Overlay Timeline Fork Diff view */
    .diff-container {
      display: flex;
      flex-direction: column;
      gap: 20px;
      padding: 8px 0;
    }

    .diff-row {
      display: grid;
      grid-template-columns: 160px 1fr;
      align-items: center;
      background: rgba(255, 255, 255, 0.01);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 14px;
      position: relative;
    }

    .diff-row.winner {
      border-color: rgba(16, 185, 129, 0.2);
      background: rgba(16, 185, 129, 0.015);
    }

    .diff-row-label {
      font-size: 11px;
      font-family: 'JetBrains Mono', monospace;
      font-weight: 600;
      color: var(--text-dim);
      border-right: 1px dashed var(--border-color);
      padding-right: 12px;
    }

    .diff-row-events {
      display: flex;
      gap: 12px;
      overflow-x: auto;
      padding-left: 16px;
    }

    .diff-badge {
      display: inline-block;
      font-size: 9px;
      padding: 1px 5px;
      border-radius: 4px;
      margin-top: 4px;
      font-weight: 600;
    }
    .diff-badge.better { background: var(--color-emerald-bg); color: var(--color-emerald); }
    .diff-badge.worse { background: var(--color-rose-bg); color: var(--color-rose); }

    /* Option A: Route Map Panel */
    .route-map-panel {
      border: 1px solid var(--border-color);
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.2);
      padding: 16px;
      position: relative;
    }

    .map-svg-wrap {
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }

    .map-overlay {
      position: absolute;
      top: 12px;
      left: 12px;
      background: rgba(11, 15, 25, 0.9);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 10px;
      font-size: 11px;
      backdrop-filter: blur(8px);
      pointer-events: none;
      width: 240px;
    }

    .map-overlay-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 4px;
    }
    .map-overlay-row span:first-child { color: var(--text-muted); }
    .map-overlay-row span:last-child { font-family: 'JetBrains Mono', monospace; color: var(--text-main); }

    /* SVG Map node styles */
    .map-node { fill: #0f172a; stroke: #223044; stroke-width: 2; }
    .map-node.active { stroke: var(--color-cyan); filter: drop-shadow(0 0 4px var(--color-cyan)); }
    .map-node-text { fill: var(--text-main); font-size: 11px; font-weight: 600; }
    .map-edge { stroke: #223044; stroke-width: 2; stroke-dasharray: 6 6; }
    .map-edge.active { stroke: var(--color-cyan); stroke-dasharray: 10 100; stroke-dashoffset: 0; }

    /* Right Inspector */
    .inspector {
      border-left: 1px solid var(--border-color);
      background: var(--bg-panel);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .inspector-header {
      height: 40px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      padding: 0 12px;
    }

    .inspector-title {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      font-weight: 700;
    }

    .inspector-content {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
    }

    .inspector-section-title {
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 6px;
      font-weight: 700;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      padding-bottom: 3px;
    }

    .inspector-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 16px;
    }

    .inspector-kv {
      background: rgba(0,0,0,0.15);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px;
    }

    .inspector-label {
      font-size: 9px;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 2px;
    }

    .inspector-value {
      font-size: 11px;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
    }

    pre {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 10px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      color: #93c5fd;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 280px;
    }

    /* Option B: Bottom Command Composer */
    .composer-panel {
      height: 118px;
      border-top: 1px solid var(--border-color);
      background: #09111d;
      padding: 12px 16px;
      display: grid;
      grid-template-columns: 240px 1fr 140px;
      gap: 16px;
      align-items: center;
      z-index: 10;
    }

    .composer-modes {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .composer-mode-btn {
      background: var(--bg-panel);
      border: 1px solid var(--border-color);
      color: var(--text-muted);
      font-size: 10px;
      font-family: 'JetBrains Mono', monospace;
      padding: 5px 8px;
      border-radius: 6px;
      cursor: pointer;
      text-align: left;
      transition: all 0.2s;
    }

    .composer-mode-btn.active {
      color: var(--color-cyan);
      border-color: rgba(6, 182, 212, 0.25);
      background: rgba(6, 182, 212, 0.08);
      box-shadow: inset 0 0 4px rgba(6, 182, 212, 0.1);
    }

    .composer-input-row {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .composer-textarea {
      width: 100%;
      height: 60px;
      background: rgba(0,0,0,0.3);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      color: var(--text-main);
      font-family: inherit;
      font-size: 12px;
      padding: 8px 12px;
      outline: none;
      resize: none;
    }
    .composer-textarea:focus {
      border-color: var(--color-cyan);
    }

    .composer-meta-selectors {
      display: flex;
      gap: 8px;
    }

    .composer-select {
      background: rgba(0,0,0,0.2);
      border: 1px solid var(--border-color);
      color: var(--text-dim);
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      width: auto;
    }

    .composer-send-btn {
      height: 48px;
      background: rgba(6, 182, 212, 0.08);
      color: var(--color-cyan);
      border: 1px solid rgba(6, 182, 212, 0.25);
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
    }

    .composer-send-btn:hover {
      background: var(--color-cyan);
      color: var(--bg-dark);
      box-shadow: 0 0 10px rgba(6, 182, 212, 0.3);
    }

    .empty-state {
      color: var(--text-muted);
      text-align: center;
      padding: 40px 0;
      font-size: 12px;
    }
  </style>
</head>
<body>

  <!-- Top Bar -->
  <header class="top-bar">
    <div class="brand-section">
      <div class="logo">Hivewire Operations</div>
      <div class="nav-links">
        <a class="active" href="/console">Console</a>
        <a href="/benchmark">Benchmark</a>
      </div>
    </div>

    <!-- Option A: Co-routing & Egress Hop Circuit -->
    <div class="egress-circuit">
      <div class="status-dot"></div>
      <span class="circuit-node model" id="modelTier">web_fetch</span>
      <span class="circuit-arrow">──(rotating)──></span>
      <span class="circuit-node egress" id="egressPool">proxy-cheap</span>
      <span class="circuit-arrow">──></span>
      <span class="circuit-node ip" id="observedIp">observed IP pending</span>
    </div>

    <div class="global-metrics">
      <div class="metric-item">
        <span class="metric-label">Runs</span>
        <span class="metric-value" id="runCount">--</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Spend est.</span>
        <span class="metric-value" id="spend" style="color: var(--color-emerald);">--</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">Success</span>
        <span class="metric-value" id="success">--</span>
      </div>
    </div>
  </header>

  <!-- Workspace Grid Layout -->
  <main class="workspace">

    <!-- Left Sidebar: Session Selectors -->
    <aside>
      <div class="sidebar-header">
        <span class="sidebar-title">Sessions & History</span>
      </div>
      <div class="sidebar-content">
        
        <div class="selector-block">
          <label for="runSelector">Active Run</label>
          <select id="runSelector">
            <option value="">Live accumulated dataset</option>
          </select>
        </div>

        <div class="selector-block">
          <label for="compareSelector">Compare Against</label>
          <select id="compareSelector">
            <option value="">No comparison</option>
          </select>
        </div>

        <div class="list-heading">Current baseline</div>
        <div class="vendor-row active">
          <span>proxy-cheap rotating</span>
          <span class="pill">Real</span>
        </div>

        <div class="list-heading">Vendors</div>
        <div id="vendors"></div>

      </div>
    </aside>

    <!-- Center Main Viewport -->
    <section class="main-viewport">
      <!-- Toolbar Tabs -->
      <div class="view-toolbar">
        <button class="tab-btn active" onclick="switchView('timeline')">Live swarm timeline</button>
        <button class="tab-btn" onclick="switchView('diff')">Overlay Fork Diff</button>
        <button class="tab-btn" onclick="switchView('route')">Egress route map</button>
      </div>

      <!-- Live Timeline -->
      <div id="timeline" class="view-panel active">
        <div class="timeline-container" id="timelineContainer">
          <div class="empty-state">Loading live timeline events...</div>
        </div>
      </div>

      <!-- Overlay Fork Diff Timeline -->
      <div id="diff" class="view-panel">
        <div class="diff-container" id="diffContainer">
          <div class="empty-state">Select a run in "Compare Against" to view overlay fork timelines.</div>
        </div>
      </div>

      <!-- Egress Route Map (Option A) -->
      <div id="route" class="view-panel">
        <div class="route-map-panel">
          <div class="map-svg-wrap">
            <svg viewBox="0 0 700 240" width="100%" height="240">
              <!-- Grid Pattern -->
              <defs>
                <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                  <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.015)" stroke-width="1"/>
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid)" />

              <!-- Connection Hops -->
              <path class="map-edge active" x1="120" y1="120" x2="350" y2="120" d="M 120 120 L 350 120" stroke-width="2" />
              <path class="map-edge active" x1="350" y1="120" x2="580" y2="120" d="M 350 120 L 580 120" stroke-width="2">
                <animate attributeName="stroke-dashoffset" values="100;0" dur="5s" repeatCount="indefinite" />
              </path>

              <!-- Node 1: Client Host -->
              <g transform="translate(120, 120)">
                <circle class="map-node active" r="28" fill="rgba(6, 182, 212, 0.08)" />
                <circle r="4" fill="var(--color-cyan)" />
                <text class="map-node-text" y="44" text-anchor="middle">Agent Client</text>
                <text y="58" text-anchor="middle" fill="var(--text-muted)" font-size="9" font-family="'JetBrains Mono', monospace">process</text>
              </g>

              <!-- Node 2: Egress Proxy Pool -->
              <g transform="translate(350, 120)">
                <circle class="map-node active" r="34" fill="rgba(99, 102, 241, 0.08)" />
                <circle r="4" fill="var(--color-indigo)" />
                <text class="map-node-text" y="48" text-anchor="middle" id="mapPool">proxy-cheap</text>
                <text y="62" text-anchor="middle" fill="var(--text-muted)" font-size="9" font-family="'JetBrains Mono', monospace" id="mapPolicy">rotating</text>
              </g>

              <!-- Node 3: Target Server -->
              <g transform="translate(580, 120)">
                <circle class="map-node" r="28" fill="rgba(255,255,255,0.01)" />
                <circle r="4" fill="var(--text-muted)" />
                <text class="map-node-text" y="44" text-anchor="middle">Destination</text>
                <text y="58" text-anchor="middle" fill="var(--text-muted)" font-size="9" font-family="'JetBrains Mono', monospace" id="mapTarget">latest</text>
              </g>
            </svg>

            <!-- Geolocation Information Overlay -->
            <div class="map-overlay">
              <h4 style="color: var(--color-cyan); margin-bottom: 8px; font-size: 10px; text-transform: uppercase;">Egress Telemetry</h4>
              <div class="map-overlay-row">
                <span>Egress Pool</span>
                <span id="overlayPool">proxy-cheap</span>
              </div>
              <div class="map-overlay-row">
                <span>Observed IP</span>
                <span id="overlayIp">pending</span>
              </div>
              <div class="map-overlay-row">
                <span>Latency</span>
                <span id="overlayLatency">--</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Right Inspector Panel -->
    <aside class="inspector">
      <div class="inspector-header">
        <span class="inspector-title">Event Tracer</span>
      </div>
      <div class="inspector-content" id="inspectorContent">
        <div class="empty-state">Select a timeline card to view traces.</div>
      </div>
    </aside>

  </main>

  <!-- Bottom Command Composer (Option B) -->
  <footer class="composer-panel">
    <div class="composer-modes">
      <button class="composer-mode-btn active" id="modeSteerBtn" onclick="setComposerMode('steer')">⚡ Steer current run</button>
      <button class="composer-mode-btn" id="modeFollowBtn" onclick="setComposerMode('follow')">⏱ Queue follow-up</button>
      <button class="composer-mode-btn" id="modeForkBtn" onclick="setComposerMode('fork')">🔁 Fork from event</button>
    </div>

    <div class="composer-input-row">
      <textarea class="composer-textarea" id="composerInput" placeholder="Intervene/steer the current running swarm agent..."></textarea>
      <div class="composer-meta-selectors">
        <select class="composer-select" id="composerModel">
          <option value="smart">Smart Tier</option>
          <option value="cheap">Cheap Tier</option>
        </select>
        <select class="composer-select" id="composerProxy">
          <option value="us">Proxy: US-West rotating</option>
          <option value="eu">Proxy: EU-Central sticky</option>
        </select>
      </div>
    </div>

    <button class="composer-send-btn" type="button" onclick="alert('Simulation: command queued to Hivewire harness control loop.')">
      Send Command
    </button>
  </footer>

  <script>
    const $=id=>document.getElementById(id);
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const pct=x=>x==null?'--':Math.round(x*100)+'%';
    const usd=x=>x==null?'--':'$'+Number(x).toFixed(4);

    let selectedRecord = null;
    let selectedRunId = '';
    let compareRunId = '';

    // Switch Composer Modes
    function setComposerMode(mode) {
      document.querySelectorAll('.composer-mode-btn').forEach(btn => btn.classList.remove('active'));
      const text = $('composerInput');
      if (mode === 'steer') {
        $('modeSteerBtn').classList.add('active');
        text.placeholder = "Intervene/steer the current running swarm agent...";
      } else if (mode === 'follow') {
        $('modeFollowBtn').classList.add('active');
        text.placeholder = "Queue a follow-up action for after the active run completes...";
      } else if (mode === 'fork') {
        $('modeForkBtn').classList.add('active');
        text.placeholder = "Create a new session fork from the selected timeline event...";
      }
    }

    // Switch Center view tabs
    function switchView(viewId) {
      document.querySelectorAll('.view-panel').forEach(panel => panel.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      
      $(viewId).classList.add('active');
      event.target.classList.add('active');
    }

    // Load Inspector
    function inspect(r) {
      selectedRecord = r;
      document.querySelectorAll('.event-card').forEach(card => card.classList.remove('active'));
      
      // Find and add active class to clicked cards in timeline
      const cards = document.querySelectorAll(`[data-id="${r.timestamp}_${r.latency_ms}"]`);
      cards.forEach(c => c.classList.add('active'));

      $('inspectorContent').innerHTML = `
        <div style="margin-bottom: 16px;">
          <h3 style="font-size: 13px; font-weight: 700; margin-bottom: 2px;">${esc(r.outcome.toUpperCase())} · ${esc(r.target_class)}</h3>
          <span class="pill">${esc(r.vendor)}</span>
        </div>

        <div class="inspector-section-title">Telemetry metrics</div>
        <div class="inspector-grid">
          <div class="inspector-kv">
            <div class="inspector-label">Latency</div>
            <div class="inspector-value" style="color: var(--color-cyan);">${r.latency_ms != null ? Number(r.latency_ms).toFixed(0) + 'ms' : '--'}</div>
          </div>
          <div class="inspector-kv">
            <div class="inspector-label">Status Code</div>
            <div class="inspector-value">${r.status_code ?? '--'}</div>
          </div>
          <div class="inspector-kv">
            <div class="inspector-label">Egress pool</div>
            <div class="inspector-value" style="color: var(--color-indigo);">${esc(r.pool || 'default')}</div>
          </div>
          <div class="inspector-kv">
            <div class="inspector-label">Egress IP</div>
            <div class="inspector-value">${esc(r.observed_ip || 'not recorded')}</div>
          </div>
        </div>

        <div class="inspector-section-title">Egress session policy</div>
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 11px; margin-bottom: 16px; color: var(--text-dim);">
          Session Policy: ${esc(r.session_policy || 'rotating')}
        </div>

        <div class="inspector-section-title">Raw JSONL tracing record</div>
        <pre>${esc(JSON.stringify(r, null, 2))}</pre>

        <div style="display: flex; gap: 8px; margin-top: 16px;">
          <button class="composer-send-btn" style="flex: 1; height: 32px;" onclick="alert('Forking branch from this checkpoint...')">Fork From Here</button>
          <button class="composer-send-btn" style="flex: 1; height: 32px; background: transparent; border-color: var(--border-color); color: var(--text-dim);" onclick="alert('Replaying event trace...')">Replay Node</button>
        </div>
      `;
    }

    // Render console updates
    function render(d) {
      const recent = d.recent || [];
      const newest = recent[0] || {};
      const vendors = d.vendors || [];
      const primaryVendor = vendors[0] || {};
      const runHistory = d.run_history || [];

      // Global circuit strip updates (Option A)
      $('runCount').textContent = d.total_runs ?? 0;
      $('spend').textContent = d.has_pricing ? usd(d.total_spend_usd) : '--';
      $('success').textContent = pct(primaryVendor.success_rate);

      $('egressPool').textContent = newest.pool || primaryVendor.vendor || 'proxy-cheap';
      $('observedIp').textContent = newest.observed_ip || 'observed IP not recorded';
      
      // Update interactive SVG Map elements
      $('mapPool').textContent = (newest.vendor || 'proxy-cheap').slice(0, 18);
      $('mapPolicy').textContent = newest.session_policy || 'rotating';
      $('mapTarget').textContent = (newest.target_class || 'latest').slice(0, 18);

      $('overlayPool').textContent = newest.pool || newest.vendor || 'proxy-cheap';
      $('overlayIp').textContent = newest.observed_ip || 'pending';
      $('overlayLatency').textContent = newest.latency_ms != null ? newest.latency_ms.toFixed(0) + 'ms' : '--';

      // Dropdown Populators
      if ($('runSelector').options.length <= 1) {
        $('runSelector').innerHTML = '<option value="">Live accumulated dataset</option>' + 
          runHistory.map(r => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${r.result_count} records</option>`).join('');
        $('runSelector').value = d.selected_run_id || selectedRunId || '';
      }
      
      if ($('compareSelector').options.length <= 1) {
        $('compareSelector').innerHTML = '<option value="">No comparison</option>' + 
          runHistory.map(r => `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${r.result_count} records</option>`).join('');
        $('compareSelector').value = compareRunId || '';
      }

      // Populate left vendors list
      $('vendors').innerHTML = vendors.map(v => `
        <div class="vendor-row ${v.vendor === primaryVendor.vendor ? 'active' : ''}">
          <span>${esc(v.vendor)}</span>
          <span class="pill">${v.runs} runs · ${pct(v.success_rate)}</span>
        </div>
      `).join('');

      // Render standard Swimlanes timeline (grouped by target_class)
      const byLane = {};
      recent.forEach(r => {
        const k = r.target_class || 'unknown';
        (byLane[k] ||= []).push(r);
      });

      $('timelineContainer').innerHTML = Object.entries(byLane).map(([lane, items]) => `
        <div class="lane">
          <div class="lane-head">
            <span>Swarm Lane: ${esc(lane)}</span>
            <span>${items.length} records</span>
          </div>
          <div class="lane-events">
            ${items.map(r => {
              const uId = `${r.timestamp}_${r.latency_ms}`;
              return `
                <div class="event-card ${esc(r.outcome)}" data-id="${uId}" onclick='inspect(${JSON.stringify(r)})'>
                  <div class="event-type">${esc(r.vendor)} · ${esc(r.pool || 'pool')}</div>
                  <div class="event-title">${esc(r.outcome.toUpperCase())} · ${r.status_code ?? '--'}</div>
                  <div class="event-meta">
                    <span>${r.latency_ms != null ? Number(r.latency_ms).toFixed(0) + 'ms' : '--'}</span>
                    <span>${esc(r.session_policy || 'rotating')}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `).join('') || '<div class="empty-state">No timeline logs recorded yet. Run benchmark to stream events.</div>';

      // Option B: Render Parallel Overlay Timeline Diff
      const compRecords = d.compare_records || [];
      if (compareRunId && compRecords.length > 0) {
        // Group compared records by target class
        const compByLane = {};
        compRecords.forEach(r => {
          const k = r.target_class || 'unknown';
          (compByLane[k] ||= []).push(r);
        });

        // Generate combined overlay track view
        const allLanes = Array.from(new Set([...Object.keys(byLane), ...Object.keys(compByLane)]));
        
        $('diffContainer').innerHTML = allLanes.map(lane => {
          const currentEvents = byLane[lane] || [];
          const comparedEvents = compByLane[lane] || [];
          
          // Simple heuristic to highlight winner based on success rate
          const curSuccess = currentEvents.filter(x => x.outcome === 'success').length / (currentEvents.length || 1);
          const compSuccess = comparedEvents.filter(x => x.outcome === 'success').length / (comparedEvents.length || 1);
          
          const isCurrentWinner = curSuccess >= compSuccess;
          
          return `
            <div style="margin-bottom: 24px;">
              <h4 style="font-size: 11px; text-transform: uppercase; color: var(--color-cyan); margin-bottom: 8px;">Swimlane: ${esc(lane)}</h4>
              <div class="diff-container">
                <!-- Track A: Current Run -->
                <div class="diff-row ${isCurrentWinner ? 'winner' : ''}">
                  <div class="diff-row-label">
                    <div>Current Run</div>
                    <span class="diff-badge ${isCurrentWinner ? 'better' : 'worse'}">
                      ${pct(curSuccess)} Success
                    </span>
                  </div>
                  <div class="diff-row-events">
                    ${currentEvents.map(r => `
                      <div class="event-card ${esc(r.outcome)}" data-id="${r.timestamp}_${r.latency_ms}" onclick='inspect(${JSON.stringify(r)})'>
                        <div class="event-type">${esc(r.vendor)}</div>
                        <div class="event-title">${esc(r.outcome.toUpperCase())}</div>
                        <div class="event-meta">
                          <span>${r.latency_ms != null ? Number(r.latency_ms).toFixed(0) + 'ms' : '--'}</span>
                        </div>
                      </div>
                    `).join('') || '<div class="empty-state" style="padding: 0;">No events in this lane</div>'}
                  </div>
                </div>

                <!-- Track B: Compared Run -->
                <div class="diff-row ${!isCurrentWinner ? 'winner' : ''}">
                  <div class="diff-row-label">
                    <div>Compared Run</div>
                    <span class="diff-badge ${!isCurrentWinner ? 'better' : 'worse'}">
                      ${pct(compSuccess)} Success
                    </span>
                  </div>
                  <div class="diff-row-events">
                    ${comparedEvents.map(r => `
                      <div class="event-card ${esc(r.outcome)}" onclick='inspect(${JSON.stringify(r)})'>
                        <div class="event-type">${esc(r.vendor)}</div>
                        <div class="event-title">${esc(r.outcome.toUpperCase())}</div>
                        <div class="event-meta">
                          <span>${r.latency_ms != null ? Number(r.latency_ms).toFixed(0) + 'ms' : '--'}</span>
                        </div>
                      </div>
                    `).join('') || '<div class="empty-state" style="padding: 0;">No events in this lane</div>'}
                  </div>
                </div>
              </div>
            </div>
          `;
        }).join('');
      } else if (compareRunId) {
        $('diffContainer').innerHTML = '<div class="empty-state">Comparison run chosen, but no records found in comparison archive.</div>';
      } else {
        $('diffContainer').innerHTML = '<div class="empty-state">Select a run in "Compare Against" dropdown in the sidebar to activate the Fork Diff timeline.</div>';
      }

      // Default select the first card in timeline if nothing is selected
      if (!selectedRecord && recent[0]) {
        inspect(recent[0]);
      }
    }

    // Periodic tick to load live data
    async function tick() {
      let url = selectedRunId ? `/data?run_id=${encodeURIComponent(selectedRunId)}` : '/data';
      if (compareRunId) {
        url += `${url.includes('?') ? '&' : '?'}compare_run_id=${encodeURIComponent(compareRunId)}`;
      }
      try {
        const res = await fetch(url); // fetch('/data')
        const data = await res.json();
        render(data);
      } catch (e) {
        $('subtitle').textContent = 'Unable to fetch data from live harness';
      }
    }

    // Listeners for dropdown updates
    $('runSelector').addEventListener('change', e => {
      selectedRunId = e.target.value;
      tick();
    });

    $('compareSelector').addEventListener('change', e => {
      compareRunId = e.target.value;
      tick();
    });

    // Initialize Page
    tick();
    setInterval(tick, 2000);
  </script>
</body>
</html>
"""


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
                compare_records_data = []
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
                        compare_records=compare_records_data,
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
