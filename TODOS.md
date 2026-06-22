# TODOS

Technical follow-ups for the co-routing wedge + benchmark harness.
(Partnership / business tracking lives outside this file.)

## Done

- [x] **A1 — egress-routed `web_fetch` MCP tool** + SSRF guard, re-validated on
  every redirect hop.
- [x] **Vendor adapter** — `proxy_template` with `{region}`/`{session_id}`,
  sticky/rotating session ids, credentials masked in response metadata.
- [x] **A2 — LiteLLM model-tier↔egress co-routing** (`litellm_corouting.py`).
  Mechanism corrected from the original plan: LiteLLM exposes no per-deployment
  proxy field; binding is *process-global*. See design.md §A2 CORRECTION.
- [x] **Benchmark harness** — runner (live jsonl append), metrics
  (success/block/error, latency, cost), self-contained HTML report, and a live
  stdlib dashboard. Runs offline against the built-in mock pools today.

## Pending — blocked on real credentials (anyIP trial incoming)

- [ ] **Phase 0: prove real egress works.** Confirm a real request actually
  changes the egress IP — `ip_echo` so `observed_ip` differs from our own,
  `rotating` varies it, `sticky` holds it. Everything to date is mock (direct
  connections), so this is the make-or-break first check.
- [ ] **anyIP API mechanics.** Map product type / geo / session to endpoint
  params + headers from their integration guide, then fill the real
  `proxy_template`s in `pools.yaml`. (Credentials + docs incoming.)
- [ ] **A2 live smoke test.** Verify an actual `litellm.acompletion` egresses
  through the bound client's IP end to end (needs a model API key + proxy cred).
- [ ] **Re-verify the DNS-rebinding SSRF fix once a real proxy is wired in.**
  Residential proxies usually resolve the destination hostname themselves via
  HTTP CONNECT, which can make the client-side IP pin a no-op. Confirm against
  the trial vendor before trusting the guard end to end.

## Pending — later, when justified by real usage

- [ ] **Automate the AG-UI round-trip as an E2E test** (Playwright or similar).
  Manual smoke is fine for a one-shot demo, not for active development.
- [ ] **Response caching for repeated `web_fetch(url, route_profile)`** — TTL
  cache keyed on `(url, route_profile)`. Premature without repeat volume.
- [ ] **CI/CD / publish pipeline for `co-routing/`** (PyPI, Docker, Releases).
  Build when a vendor actually wants to install it themselves.
