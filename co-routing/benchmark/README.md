# Hivewire egress benchmark

Measures **which IP type / vendor / region succeeds against which class of
target**, plus latency and cost per successful fetch, and appends every run to a
jsonl dataset that accumulates over time so trends are visible across days.

## Run it

```bash
cd co-routing
cp benchmark/targets.yaml.example benchmark/targets.yaml   # edit as needed
uv run python -m benchmark.runner                          # appends benchmark/results.jsonl
uv run python -m benchmark.metrics                         # aggregate report (terminal)
uv run python -m benchmark.report                          # -> benchmark/report.html (shareable)
```

For repeatable scheduled runs, copy the profile example and invoke a named
profile from your scheduler:

```bash
cp benchmark/profiles.yaml.example benchmark/profiles.yaml
uv run python -m benchmark.runner --profile weekly-proxycheap-baseline
```

Profiles are intentionally declarative. They define cadence, config, output,
and archive paths; cron, launchd, GitHub Actions, or another scheduler decides
when to call the runner.

On macOS, generate a launchd plist without installing it:

```bash
../setup_hivewire_benchmark_scheduler.sh
```

Or call the generator directly:

```bash
uv run python -m benchmark.scheduler \
  --profile weekly-proxycheap-baseline \
  --out ~/Library/LaunchAgents/com.hivewire.benchmark.weekly-proxycheap-baseline.plist
```

Inspect the plist first. If it looks right, install it manually:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hivewire.benchmark.weekly-proxycheap-baseline.plist
```

From the repo root, the guarded install/uninstall wrappers are:

```bash
HIVEWIRE_CONFIRM_INSTALL=install ./install_hivewire_benchmark_scheduler.sh
HIVEWIRE_CONFIRM_UNINSTALL=uninstall ./uninstall_hivewire_benchmark_scheduler.sh
```

Each runner execution also writes an evidence package:

```text
benchmark/runs/<run_id>/
  manifest.json     # config/pricing hashes, timing, vendors, pools, outcomes
  results.jsonl     # only the records produced by that execution
  summary.json      # aggregate track metrics for that execution
```

`report.html` is one self-contained page (inline CSS + SVG, no external
requests, aggregate numbers only — no individual IPs) you can open locally or
publish on GitHub Pages. If the data came from mock pools, the page says so
loudly so a mock run can't masquerade as a real benchmark.

Default config runs against the built-in **mock pools** (direct connections, no
credentials) so the plumbing is verifiable today. `results.jsonl` and
`benchmark/runs/` are gitignored — the dataset stays local.

## When real credentials land

1. Add real pools to `pools.yaml` (templates in `../vendors.yaml.example`).
2. **Phase 0 first** — confirm a real request actually changes the egress IP
   before trusting any numbers: every track has `ip_echo: true`, so check the
   `observed_ip` field differs from your own IP, that `rotating` varies it and
   `sticky` holds it.
3. Swap the `pool:` names in `targets.yaml` to the real pools and re-run the
   **identical** config. Same methodology, now over real egress.

## Metrics

Grouped by `(vendor, target_class)`:

- **success / block / error rate** — a 200 carrying a captcha page counts as
  *blocked*, not success (`classify_outcome`).
- **latency p50 / p95** over successful fetches.
- **KB/succ** — bytes per successful fetch. The proxy is billed per GB, so this
  is the real cost proxy; lower is cheaper. Ties directly to the project thesis
  (traditional crawl cheaper than AI-sandbox overhead).
- **unique IPs** — egress IP diversity (needs `ip_echo` targets).

The report also prints each vendor's success-rate delta **vs the proxy-cheap
control** per target class.

## Methodology discipline

Fix the config (targets, runs, timeout) **before** spending GB — changing it
mid-run produces data you can't compare. Keep a consistent control vendor on the
same targets so every comparison is apples-to-apples.
