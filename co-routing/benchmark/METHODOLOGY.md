# Egress benchmark — methodology

A fixed, pre-registered protocol for comparing egress pools. "Pre-registered"
means the rules below are decided **before** any paid traffic is run, so results
can't be shaped after the fact by changing targets, metrics, or thresholds. Any
change after the first real run is logged in the Change log at the bottom.

## 1. What is measured

For each egress configuration, against a fixed set of targets:

- **success / block / error rate** (classification in §5)
- **latency** p50 / p95 over successful fetches
- **bytes per successful fetch** (KB/succ) and **estimated spend** ($/GB ×
  total bytes, incl. failures) and **$/1k successful fetches** (cost efficiency)
- **egress IP behaviour**: unique IPs observed; for sticky, IP stability; for
  rotating, IP variation

The headline question is **cost-per-successful-fetch and success rate, per track,
each vendor vs the control** — not raw speed.

## 2. Tracks and product mapping

Three use-case tracks, each run with the comparable product on **both** vendors
so every comparison is apples-to-apples:

| Track | anyIP product | Control (proxy-cheap) | session |
|-------|---------------|------------------------|---------|
| `high-volume`  | rotating mixed res/mobile | residential rotating | rotating |
| `geo`          | residential + country lock | residential + country | rotating |
| `high-trust`   | mobile + sticky | mobile/residential sticky | sticky |

The `rotating mixed` ↔ `residential rotating` mapping is imperfect (anyIP mixes
mobile in; proxy-cheap's closest product is residential rotating). This is noted
in the report rather than hidden — it's a real limit of cross-vendor comparison.

## 3. Target sets

Targets are fixed per track and **identical across vendors**. Tiered by what
each tier can actually measure:

**Tier A — calibration (all tracks).** Neutral infrastructure endpoints. These
do not deploy anti-bot, so success here measures connectivity / latency / IP
behaviour, *not* evasion.
- `https://api.ipify.org?format=json` (IP echo — drives `observed_ip`)
- `https://httpbin.org/get`, `https://httpbin.org/headers`

**Tier B — scraping sandboxes (`high-volume`).** Purpose-built for scraping
practice, no ToS concern, safe at volume.
- `http://books.toscrape.com/`, `http://quotes.toscrape.com/`

**Tier C — difficulty / anti-bot (`high-trust`).** Realistic anti-bot targets
are where mobile/sticky should win — but hammering commercial sites carries ToS
and legal risk. **No commercial anti-bot target is baked into this protocol.**
Adding any Tier-C target requires a deliberate per-target ToS/legal check first,
logged in the Change log. Until then `high-trust` runs Tier-A only and is
labelled "infra-only, not yet an anti-bot test" in the report.

**Geo verification (`geo`).** Region correctness is checked in analysis by
geolocating the recorded `observed_ip` and comparing its country to the
requested `region` — not by hammering geo-locked commercial sites.

## 4. Run parameters

- `runs_per_target`: **≥ 20** per (target, track) for a real run. Rationale: at a
  true 50% rate, 20 runs give a ~±22pp 95% CI; bump to 40+ for rates near a
  decision boundary. (The example config ships fewer for quick offline checks.)
- `concurrency`: 5 (polite to targets; avoids self-inflicted rate-limiting)
- `timeout_s`: 25
- Each track runs the **same** target set on vendor and control, back to back,
  same day, to limit target-side drift between the two.

## 5. Outcome classification (frozen)

Implemented in `runner.classify_outcome`:

- **error** — no HTTP response (connection refused, timeout, proxy failure)
- **blocked** — status in {403, 429, 503}, OR any other non-2xx, OR a 2xx whose
  body contains an anti-bot marker (captcha / "access denied" / "are you a
  robot" / cloudflare challenge / "unusual traffic" / …)
- **success** — 2xx with no block marker

A 2xx captcha/challenge page is **blocked, not success** — this distinction is
the whole point.

## 6. Phase 0 gate (must pass before any real run counts)

Before trusting any real-egress numbers, confirm the proxy actually works:

1. `observed_ip` from a real pool **differs from the operator's own IP**.
2. `rotating` produces **different** IPs across requests.
3. `sticky` **holds** one IP across requests within the session.
4. Re-check the DNS-rebinding SSRF guard against the real proxy: residential
   proxies often resolve the destination hostname themselves via HTTP CONNECT,
   which can make the client-side IP pin a no-op. Confirm behaviour before
   relying on the guard end to end.

A dataset that hasn't passed Phase 0 is calibration only and labelled as such.

## 7. Honesty constraints

- **Spend is an estimate, not an invoice** — response bytes only; reconcile
  against each vendor's usage dashboard.
- **Mock vs real** — mock-pool runs are labelled MOCK in report/dashboard and
  never reported as a vendor result.
- **The control's product may not perfectly mirror the vendor's** — noted per
  track (§2), not hidden.
- Methodology is fixed before the first real run; deviations go in the Change
  log below with a date and reason.

## Change log

- 2026-06-22 — protocol drafted (pre-registration), no real runs yet.
- 2026-06-22 — proxy-cheap integration verified end-to-end (Phase 0 passed:
  rotating varies IP, sticky holds). Confirmed connection grammar: one base
  credential + password-suffix modifiers `_country-<cc>` (geo) and
  `_session-<id>` (sticky); rotating uses a fresh session per request. Format
  recorded in vendors.yaml.example and docs/vendor-integration.md. Preliminary
  proxy-cheap baseline run at 10 runs/target (below the ≥20 formal bar — not yet
  a publishable result).
