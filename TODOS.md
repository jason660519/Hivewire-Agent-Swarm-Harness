# TODOS

Deferred items from the Co-Routing Wedge design
(`~/.gstack/projects/jason660519-Hivewire-Agent-Swarm-Harness/jasonmacbbookpro-main-design-20260616-194459.md`)
and from `/plan-eng-review` (2026-06-17).
Not blocking the A1 demo — tracked here so they don't get lost.

- [x] **A2 — LiteLLM proxy-config co-routing.** ~~Fast-follow~~ — pulled
  forward into this week's scope (T6) per `/plan-eng-review`'s outside-voice
  tension: Codex argued a week-1 demo without model-tier binding doesn't
  actually demonstrate co-routing, only egress selection. Bind `model_tier`
  to a region's proxy via a LiteLLM `model_list` entry. Precondition: only
  intercepts runtimes that route model calls through a LiteLLM (or
  OpenAI-compatible) endpoint rather than calling provider SDKs directly.
- [ ] **Second proxy-vendor contact (business).** anyIP's original proposal
  is unanswered. If it stays silent after the A1 demo follow-up, identify
  and approach a second vendor for an actual partnership conversation —
  distinct from the trial account below, which is just for technical proof.
- [ ] **anyIP API mechanics.** Rotation/session/auth shape for anyIP's
  actual API is unknown until their docs are reviewed or the partner
  responds — needed before the egress provider can target anyIP
  specifically (a different, generic trial vendor is used for this week's
  demo instead — see T3).
- [ ] **Re-verify the DNS-rebinding SSRF fix once a real proxy is wired
  in.** The fix approved this session (resolve hostname once, pass the
  resolved IP into httpx's transport) assumes client-side DNS resolution.
  Codex (outside voice) flagged that most residential proxies resolve the
  destination hostname themselves via HTTP CONNECT, which could make the
  client-side fix a no-op once routed through a real proxy. Confirm which
  model the chosen trial vendor (T3) uses before trusting the guard end to
  end.
- [ ] **Automate the AG-UI Dojo round-trip as a real E2E test.** This week
  it's a manual smoke test only (agent → MCP `web_fetch` → Dojo UI). Worth
  automating (Playwright or similar) once co-routing is validated and under
  active, ongoing development — manual coverage is fine for a one-shot demo,
  not for a codebase you keep changing.
- [ ] **Response caching for repeated `web_fetch(url, route_profile)`
  calls.** A simple TTL cache keyed on `(url, route_profile)` would save
  proxy traffic/cost. Premature for a single demo with no repeat volume —
  revisit once there's real usage to justify it.
- [ ] **Full CI/CD / publish pipeline for `co-routing/`** (PyPI, Docker,
  GitHub Releases). This week only needs "clone and run." Build this out
  once anyIP (or another vendor) actually wants to install it themselves —
  building it now is investing in distribution for a demand that isn't
  confirmed yet.
