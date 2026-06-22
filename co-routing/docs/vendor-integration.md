# Integrating a proxy vendor

How to wire a real proxy vendor into the co-routing harness and verify it works.
Generic process plus the gotchas that actually bite. Per-vendor connection
grammars live in [`../vendors.yaml.example`](../vendors.yaml.example).

## The process

1. **Provision a proxy.** Buy/activate the product on the vendor (residential,
   mobile, etc.). Credit alone isn't enough — you need an *active* proxy.
2. **Get the connection details.** Often these are **not** in the vendor's REST
   API — the management API may only return account/auth info while the actual
   gateway `host:port` lives in a dashboard "generate credentials" screen.
   Don't assume the API gives you a usable proxy URL.
3. **Put the secret in `.env`, not in `pools.yaml`.** Add the full proxy URL:
   ```
   MYVENDOR_URL=http://user:pass@gateway.host:port
   ```
4. **Reference it from `pools.yaml`** — the file holds the var name, `.env`
   holds the value:
   ```yaml
   pools:
     myvendor:
       region: us
       mock: false
       proxy_url: "${MYVENDOR_URL}"
   ```
   `${VAR}` is expanded lazily (only when that pool is actually used), so an
   unset var only errors for the pool you use — not every pool in the file.
5. **Verify with Phase 0** before trusting any data (next section).

For region/session-aware vendors, use `proxy_template` with `{region}` /
`{session_id}` instead of a fixed `proxy_url` (see vendors.yaml.example).

## Phase 0 — prove it actually works

Mock pools are direct connections; a real proxy must change the egress IP.
Fetch an IP-echo endpoint (e.g. `https://api.ipify.org?format=json`) through the
pool and check:

- **egress IP differs from your own IP** (your IP isn't leaking).
- **rotating** → IP varies across requests.
- **sticky** → IP holds across requests.

The benchmark records `observed_ip` per run (set `ip_echo: true` on the track),
so this is visible in the results.

## Gotchas that actually bite

- **Don't trust the label — measure the behaviour.** A credential set to
  "sticky" that still rotates means a config detail is missing (see next).
  Verify rotating-vs-sticky empirically; don't assume.
- **Copy the *whole* credential, including any session/option suffix.** Some
  vendors (e.g. proxy-cheap) encode country/session/ttl as a **suffix on the
  password**. The per-field "copy password" button gives only the base password
  — paste that and a "sticky" credential silently rotates. Copy the full proxy
  URL from the vendor's CLI/connection-string field instead.
- **Trim the copied string at the port.** Vendor "CLI command" examples look
  like `curl -x http://...:8080 https://target`. Copy only up to `:8080` — if
  the trailing target URL comes along, the proxy URL fails to parse
  (`Invalid port: '8080 https:'`).
- **One base credential can serve several modes.** Vendors that use
  password/username modifiers often let a single base credential do rotating,
  sticky, and geo by varying the suffix — you may not need to generate a
  separate credential per mode.
- **SSRF guard through a proxy is advisory.** A residential proxy resolves the
  destination hostname itself, so client-side DNS pinning becomes a pre-check,
  not a binding pin. The risk model also changes: requests egress from the
  proxy's network, so they can't reach your localhost / cloud metadata / intranet.
  The direct (mock) path keeps the full pin.
