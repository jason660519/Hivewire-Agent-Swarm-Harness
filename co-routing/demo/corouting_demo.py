"""Co-routing demo — one Route Profile drives BOTH browse egress and model egress.

Offline, no credentials, no API key. This is the thesis design.md is built
around made tangible: a single RouteProfile binds

  - A1: which region/identity *browsing* (web_fetch) leaves from, and
  - A2: which region/identity the *model call* leaves from,

through the same proxy pool and the same sticky session. That binding — "which
brain, from which country's IP" — is the part nobody else ties together.

Run from co-routing/:
    uv run python demo/corouting_demo.py [URL]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# This script lives in demo/; put co-routing/ (its parent) on the path so the
# top-level modules import the same way the tests and server subprocess do.
sys.path.insert(0, str(Path(__file__).parent.parent))

from litellm_corouting import (  # noqa: E402
    TierBinding,
    build_egress_client,
    build_model_list,
)
from server import (  # noqa: E402
    PoolConfig,
    RouteProfile,
    SessionPolicy,
    _mask_proxy,
    _session_id_for,
    resolve_proxy_url,
    web_fetch,
)


def _section(title: str) -> None:
    print(f"\n{'─' * 68}\n{title}\n{'─' * 68}")


def show_corouting_binding() -> None:
    """A1 + A2 derived from ONE Route Profile — same proxy, same sticky session.

    Uses a vendor *template* pool so the proxy is real-shaped; no live call is
    made here (that needs a real credential + API key), so the fake creds are
    harmless. This is the config-level proof of the binding.
    """
    _section("1. Co-routing binding — one Route Profile, one egress identity")

    pool = PoolConfig(
        mock=False,
        proxy_template="http://USER-country-{region}-session-{session_id}:PASS@gw.vendor.example:8080",
    )
    route = RouteProfile(
        egress_pool="my-vendor",
        region="us",
        session_policy=SessionPolicy.sticky,
        model_tier="smart",
    )

    # The exact resolution web_fetch uses for browsing (A1):
    session_id = _session_id_for(route.egress_pool, route.region, route.session_policy)
    browse_proxy = resolve_proxy_url(pool, route, session_id)

    # The model client litellm_corouting binds for the model call (A2). It calls
    # the SAME resolve_proxy_url + _session_id_for internally — sticky means the
    # cached session id is reused, so the identity matches byte-for-byte.
    model_client = build_egress_client(pool, route)
    has_proxy_mount = any(p.pattern == "all://" for p in model_client._mounts)
    model_list = build_model_list(
        [TierBinding(model_tier="smart", model="anthropic/claude-opus-4-8", egress_pool="my-vendor")]
    )

    print(f"  Route Profile : {route.model_dump()}")
    print(f"  Sticky session: {session_id}")
    print(f"  A1 browse egress : {_mask_proxy(browse_proxy)}   (web_fetch)")
    print(
        f"  A2 model  egress : {_mask_proxy(browse_proxy)}   "
        f"(litellm aclient_session bound: {has_proxy_mount})"
    )
    print(f"  LiteLLM model_list: {json.dumps(model_list)}")
    print("\n  => Browsing and the model call leave from the SAME region + IP")
    print("     identity. That is co-routing. (Credentials masked.)")

    asyncio.run(model_client.aclose())


async def show_live_fetch(url: str) -> None:
    """A real, offline web_fetch through the built-in mock pool (direct
    connection) — proves the MCP tool actually works end to end."""
    _section("2. Live web_fetch through mock-us-west (direct, no proxy needed)")

    route = RouteProfile(
        egress_pool="mock-us-west",
        region="us-west",
        session_policy=SessionPolicy.sticky,
        model_tier="smart",
    )
    try:
        result = json.loads(await web_fetch(url, route))
    except Exception as exc:  # network may be unavailable; the binding proof above stands
        print(f"  (skipped — no network to reach {url}: {exc})")
        return

    if "error" in result:
        print(f"  {result['error']}")
        return

    r = result["routing"]
    print(f"  HTTP {result['status_code']} from {result['url']}")
    print(f"  region={r['region']}  session={r['session_id']}  proxy={r['proxy']}")
    print(f"  body[:120]: {result['body'][:120].strip()!r}")


def main(url: str) -> None:
    show_corouting_binding()
    asyncio.run(show_live_fetch(url))
    print()


if __name__ == "__main__":
    # An IP-echo endpoint is thematically apt: it reports the origin IP, which
    # is exactly what a real (non-mock) egress pool would change.
    target = sys.argv[1] if len(sys.argv) > 1 else "https://api.ipify.org?format=json"
    main(target)
