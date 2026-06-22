# Hivewire Benchmark Moat

Hivewire Benchmark is the evidence layer for egress decisions. It is not just a
dashboard. Its job is to make proxy and routing quality measurable,
repeatable, and auditable over time.

## Thesis

The moat is a growing benchmark corpus:

- Same tracks.
- Same classifier.
- Same pricing assumptions.
- Same raw JSONL record format.
- Same archived run package.
- Same UI for live, historical, and delta views.

That makes every vendor or egress policy comparable against the same baseline.
Today the real baseline is proxy-cheap. Future vendors should only be added
when they can run through the same harness.

## Local Entry Points

From the repo root:

```bash
./open_hivewire_console.sh
```

This opens the single-port local dashboard:

- `http://127.0.0.1:8799/` for the home page.
- `http://127.0.0.1:8799/console` for the operator console.
- `http://127.0.0.1:8799/benchmark` for benchmark evidence.
- `http://127.0.0.1:8799/data` for the JSON data API.

## Run Evidence Package

Every benchmark runner execution appends to the live dataset and writes an
evidence package:

```text
co-routing/benchmark/runs/<run_id>/
  manifest.json
  results.jsonl
  summary.json
```

`manifest.json` records reproducibility metadata:

- run id and timestamps
- config path and SHA-256
- pricing path and SHA-256
- vendors, pools, target classes
- result count and outcome counts
- mock vs real flag

`results.jsonl` contains only the records from that execution. `summary.json`
contains aggregate track metrics for that execution.

## Dashboard Views

The benchmark page currently supports:

- Live accumulated dataset view.
- Archived run selector.
- Run-to-run delta against a selected baseline.
- Vendor scorecard.
- Track evidence table.
- Latest manifest panel.
- Scheduler status panel.

The delta table compares each `vendor x target_class` on:

- success rate delta
- p95 latency delta
- estimated dollars per 1k successful fetches

## Scheduler Flow

Profiles are declarative and live in:

```text
co-routing/benchmark/profiles.yaml
```

The committed template is:

```text
co-routing/benchmark/profiles.yaml.example
```

Prepare the local scheduler files without installing launchd:

```bash
./setup_hivewire_benchmark_scheduler.sh
```

Install only after reviewing the generated plist:

```bash
HIVEWIRE_CONFIRM_INSTALL=install ./install_hivewire_benchmark_scheduler.sh
```

Uninstall:

```bash
HIVEWIRE_CONFIRM_UNINSTALL=uninstall ./uninstall_hivewire_benchmark_scheduler.sh
```

The setup script is intentionally a dry run. It creates `profiles.yaml` if
needed and writes a launchd plist, but it does not install it.

## Data Safety

Generated benchmark data stays local:

- `co-routing/benchmark/results.jsonl`
- `co-routing/benchmark/runs/`
- `co-routing/benchmark/logs/`
- `co-routing/benchmark/profiles.yaml`

These are ignored by git. Commit templates, methodology, code, and tests, not
private run data or local credentials.

## Design Rules

1. Mock data must be clearly labeled and cannot masquerade as real proxy
   evidence.
2. New vendors must use the same track methodology before being compared.
3. Cost metrics include failed and blocked bytes because proxy bandwidth is
   still billed.
4. CAPTCHA or challenge responses count as blocked, even if HTTP status is 200.
5. Historical comparison should favor run packages over ad hoc screenshots.

## Next Useful Extensions

- Add more archived real proxy-cheap runs to create a visible time series.
- Add a small trend line for success rate and p95 latency per target class.
- Add a publishable evidence report generated from one archived run.
- Add vendor adapters only when a second vendor can run through the same tracks.
