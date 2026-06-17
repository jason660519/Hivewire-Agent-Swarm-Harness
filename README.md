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

## Quick start (runs offline, no API key)

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

Early / research preview (`0.0.1`). Core verified end-to-end: AG-UI event store
with replay + fork, LiteLLM cost routing (smart/cheap tiers), swarm, auto-
reloading sandboxed extensions, MCP / prompt / theme extensions, cross-session
memory, and an ACP adapter (use Hivewire from Zed / JetBrains / Neovim).

## License

TBD.

---

> Note: this repository is the public codebase. Internal strategy and business
> documents are intentionally excluded via `.gitignore`.
