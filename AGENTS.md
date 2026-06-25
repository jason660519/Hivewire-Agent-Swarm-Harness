# AGENTS.md

Project instructions for Codex/OpenAI agents and other coding assistants working
in this repository. Keep this file provider-neutral; provider-specific files
such as `GEMINI.md` should point here instead of duplicating these rules.

This file is project scope. Cross-project personal preferences belong in the
user/global instruction scope, such as `~/.codex/AGENTS.md` or
`~/.gemini/GEMINI.md`.

## Project Shape

- Hivewire is a provider-agnostic agent swarm harness concept.
- The runnable code currently lives in `co-routing/`.
- The full harness described in roadmap sections is not yet implemented in this
  repository. Treat roadmap text as design direction, not shipped behavior.
- Public product and process docs live under `docs/`. Internal strategy or
  business material may be intentionally excluded by `.gitignore`.
- `DESIGN.md`, when present, is the approved design contract. Do not silently
  work around it; surface conflicts before changing behavior.
- `docs/project-process/todos.md` tracks technical follow-ups for the
  co-routing wedge and benchmark harness.

## Working Rules

- Before non-trivial implementation work, orient on the relevant docs:
  `DESIGN.md` if present, `README.md`, `docs/project-process/todos.md`, and
  the relevant `co-routing/` files.
- Keep changes small, verifiable, and aligned with nearby code style.
- Preserve unrelated user changes. If the working tree is dirty, work around
  unrelated files instead of reverting them.

## Commands

Run Python work from `co-routing/` with `uv`.

```bash
cd co-routing
uv sync
uv run pytest
```

Useful demos:

```bash
cd co-routing
uv run python demo/corouting_demo.py
uv run python demo/demo.py https://httpbin.org/get
```

Benchmark/dashboard commands:

```bash
cd co-routing
uv run python -m benchmark.runner
uv run python -m benchmark.report
uv run python -m benchmark.dashboard
```

From the repository root, the local console launcher is:

```bash
./open_hivewire_console.sh
```

The default console URL is `http://127.0.0.1:8799/`.

## Verification

- Run the smallest relevant verification immediately after behavior changes.
- For `co-routing/`, prefer `uv run pytest` or a focused pytest target from
  inside `co-routing/`.
- Browser-visible UI/dashboard changes should be checked in a real browser when
  possible, with no visible dev errors.
- If verification requires credentials, network access, or external services,
  say exactly what was skipped and why.

## Co-routing Notes

- The MCP `web_fetch(url, route_profile)` path must keep SSRF protection active
  for the original URL and every redirect hop.
- Route profile behavior binds egress pool, region, and session policy. Vendor
  credentials must be masked in logs, reports, and response metadata.
- Sticky and rotating proxy behavior is vendor-specific. Do not invent session
  or country suffixes without checking the vendor integration docs.
- LiteLLM proxy binding is process-global in this project. Do not imply
  per-deployment proxy isolation unless the implementation has changed and is
  verified.

## Agent Instruction Maintenance

- `AGENTS.md` is the canonical shared instruction file for this repository.
- `GEMINI.md` is only a Gemini CLI entry point and should stay as a short
  pointer to this file.
- If Claude-specific project memory is added later, prefer a short `CLAUDE.md`
  pointer to `AGENTS.md` unless Claude-only behavior genuinely needs separate
  instructions.
- Keep project rules here and personal cross-project preferences in global
  agent files. Do not duplicate the same long rule set in both scopes.
