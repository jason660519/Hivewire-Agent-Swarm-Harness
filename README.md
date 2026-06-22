# Hivewire — Agent Swarm Harness

> There are many agent harnesses, but this one is yours.

A minimal, **provider-agnostic agent swarm harness**. Hivewire decouples the
agent runtime from the UI and lifts the interaction into an **observable,
resumable, versioned protocol layer** — wire-compatible with
[AG-UI](https://docs.ag-ui.com), with Hivewire adding an append-only event
store, **fork**, and **replay**.

Adapt Hivewire to your workflows, not the other way around.

## Why

- **Don't get locked to one provider.** Every model call goes through a LiteLLM
  gateway, so Anthropic / OpenAI / Gemini and local backends (Ollama,
  llama.cpp, vLLM) are a config change, not a code change. Route cheap tasks to
  a cheap/local model.
- **Egress-agnostic too (roadmap).** A neutral egress layer makes any proxy/IP
  provider a config change as well — and **region-aware co-routing** binds
  *model* and *egress* together so each sub-agent picks both "which brain" and
  "from which country/identity it connects out."
- **Observable / resumable / versioned.** Sessions are append-only event logs.
  Reconnect and replay from any point; fork a new branch from any step.
- **Auto-reloading, sandboxed extensions.** Write or change an extension and it
  hot-reloads — no restart. A capability allow-list gates what each extension
  can do; run them in a subprocess or a network-isolated Docker sandbox.

## Architecture

```
UI host (TS/React, AG-UI client)
        │  AG-UI events over SSE
Protocol Gateway (Python / FastAPI)   ← append-only store, fork, replay
        │
Agent Runtime (Python)                ← agent loop, steer/follow-up, extensions
        │
        ├─► LLM Gateway   (LiteLLM)    ← Anthropic / OpenAI / Gemini · Ollama / llama.cpp / vLLM
        └─► Egress Gateway (roadmap)   ← any proxy/IP provider (HTTP/HTTPS/SOCKS5)
```

## What runs today: the co-routing wedge

The runnable code in this repo is **`co-routing/`** — a harness-agnostic MCP
tool server that routes `web_fetch(url, route_profile)` through a selected
egress pool, with an SSRF guard on every URL and redirect hop. It plugs into
any AG-UI / MCP runtime (LangGraph, Mastra, the Anthropic Agent SDK, …) with no
changes to that runtime's code. The full harness below is roadmap.

```bash
cd co-routing
uv sync
uv run pytest                                 # 63 tests, all offline

# The thesis in one run: ONE Route Profile drives both browse egress (A1) and
# model egress (A2) — same region, same IP identity. No credentials, no API key.
uv run python demo/corouting_demo.py

# Just the A1 MCP round-trip (connects as an MCP client over stdio)
uv run python demo/demo.py https://httpbin.org/get
```

`corouting_demo.py` shows the co-routing binding (browsing and the model call
leave from the same proxy/region/sticky session) plus a live `web_fetch`
through the built-in `mock-us-west` pool. `demo.py` connects as an MCP client —
the same protocol any AG-UI-compatible runtime uses — and prints the routing
metadata + body.

### Plug in your proxy vendor (one config block, no code)

A residential-proxy vendor becomes a Route Profile field — not a code change.
Copy a block from [`co-routing/vendors.yaml.example`](co-routing/vendors.yaml.example)
into `co-routing/pools.yaml`, fill in your credentials, and you're routing:

```yaml
pools:
  my-vendor:
    mock: false
    # {region} <- RouteProfile.region; {session_id} <- per-request token
    proxy_template: "http://USER-country-{region}-session-{session_id}:PASS@gw.vendor.example:8080"
```

Then any agent calls it with a Route Profile:

```jsonc
web_fetch("https://example.com", {
  "egress_pool": "my-vendor",
  "region": "us",            // passed verbatim — use the code your vendor expects
  "session_policy": "sticky" // sticky = same IP for the session; rotating = new IP per call
})
```

`session_policy=sticky` reuses one upstream IP for the process's lifetime;
`rotating` requests a fresh IP each call. Credentials are stripped from the
response metadata. Per-vendor connection grammars are in
[`vendors.yaml.example`](co-routing/vendors.yaml.example); the step-by-step
wiring + verification process (and the gotchas) is in
[`docs/vendor-integration.md`](co-routing/docs/vendor-integration.md).

### Benchmark egress across pools

[`co-routing/benchmark/`](co-routing/benchmark/) measures egress
success/block rate, latency, and cost per successful fetch across pools, appends
each run to a jsonl dataset, and renders a self-contained HTML report (plus a
live dashboard). Runs offline against the mock pools; swap in real pools to
benchmark them under the identical methodology. See
[benchmark/README.md](co-routing/benchmark/README.md).

```bash
uv run python -m benchmark.runner      # run tracks -> results.jsonl
uv run python -m benchmark.report      # -> report.html
uv run python -m benchmark.dashboard   # live view at http://127.0.0.1:8799
```

## Full harness (roadmap — not yet in this repo)

```bash
cd hivewire
uv sync
uv run hivewire           # serves http://127.0.0.1:8787

# UI (separate terminal)
cd ui
npm install
npm run dev               # opens http://127.0.0.1:5173
```

Type a message: **Enter = steer** (interrupts current work), **Alt+Enter =
follow-up** (queued). With no `HIVEWIRE_MODEL` set, a mock model replies so you
can see the full event stream offline.

### Swarm (parallel sub-agents)

```
swarm: research auth | draft schema | review tests
```

A parent run fans out one sub-agent per subtask (concurrently). Each sub-agent
is its own run, linked back through AG-UI `parentRunId`.

## Status

Early / research preview (`0.0.1`).

**In this repo, working and tested today:** the co-routing wedge — an MCP
`web_fetch` tool with region/session-aware egress routing, a vendor adapter
layer (`proxy_template`), an SSRF guard re-validated on every redirect hop, a
working end-to-end MCP demo, and the A2 model-tier↔egress binding layer
(`litellm_corouting.py`): build a LiteLLM `model_list` and route a tier's model
calls through the same proxy pool as browsing. 43 tests, all offline.

> A2 caveat (verified against LiteLLM docs): LiteLLM binds proxies
> **process-globally** (env vars or the global `aclient_session`), not
> per-deployment — so one tier↔region binding is per process. For concurrent
> multi-region routing, run one router per region. See [`design.md`](design.md) §A2.

**Designed, not yet built** (see [`design.md`](design.md)): the full harness —
AG-UI event store with replay + fork, swarm, auto-reloading sandboxed
extensions, cross-session memory, ACP adapter. These are the roadmap, not
shipped here yet.

## License

TBD.

---

> Note: this repository is the public codebase. Internal strategy and business
> documents are intentionally excluded via `.gitignore`.
