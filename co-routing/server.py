"""Hivewire co-routing MCP tool server — A1 demo.

Exposes web_fetch(url, route_profile) as an MCP tool.
RouteProfile selects an egress pool by name, region, and session_policy.

Pool config lives in pools.yaml (see pools.yaml.example); if that file is
absent the built-in mock pools are used so the demo runs without credentials.

SSRF guard: validate_fetch_url is called on every URL *including* every
redirect hop — re-validation is this module's responsibility (ssrf_guard.py
validates a single URL only, per its module docstring).

When a real HTTP CONNECT proxy is wired in, the proxy resolves the destination
hostname itself, so client-side DNS pinning becomes advisory only on that path.
See TODOS.md: "Re-verify the DNS-rebinding SSRF fix once a real proxy is wired in."
"""
from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from ssrf_guard import SSRFBlockedError, request_kwargs_for, validate_fetch_url

MAX_REDIRECTS = 10

_POOLS_FILE = Path(os.environ.get("POOLS_FILE", Path(__file__).parent / "pools.yaml"))


# ---------------------------------------------------------------------------
# Route profile schema
# ---------------------------------------------------------------------------

class SessionPolicy(str, Enum):
    rotating = "rotating"
    sticky = "sticky"


class RouteProfile(BaseModel):
    egress_pool: str
    region: str
    session_policy: SessionPolicy = SessionPolicy.rotating


# ---------------------------------------------------------------------------
# Pool registry
# ---------------------------------------------------------------------------

class PoolConfig(BaseModel):
    region: str
    mock: bool = False
    proxy_url: str | None = None


def _builtin_mock_pools() -> dict[str, PoolConfig]:
    """Built-in mock pools — direct connections, clearly labeled in metadata."""
    return {
        "mock-us-west": PoolConfig(region="us-west", mock=True),
        "mock-asia": PoolConfig(region="asia", mock=True),
        "mock-eu": PoolConfig(region="eu", mock=True),
    }


def load_pools(path: Path = _POOLS_FILE) -> dict[str, PoolConfig]:
    if not path.exists():
        return _builtin_mock_pools()
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {name: PoolConfig(**cfg) for name, cfg in raw.get("pools", {}).items()}


# ---------------------------------------------------------------------------
# Core fetch — redirect-hop SSRF re-validation is here
# ---------------------------------------------------------------------------

async def _fetch_with_ssrf_guard(
    url: str,
    proxy_url: str | None,
) -> tuple[httpx.Response, int]:
    """Fetch url, calling validate_fetch_url on the initial URL and every
    redirect Location before following it."""
    client_kwargs: dict[str, Any] = {"follow_redirects": False}
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        current_url = url
        redirect_hops = 0

        while True:
            target = validate_fetch_url(current_url)

            if proxy_url:
                # Proxy resolves the hostname; send original URL (not pinned IP).
                # SSRF guard still rejects private/reserved schemes and ranges
                # but cannot guarantee what the proxy resolves to.
                req_kwargs: dict[str, Any] = {
                    "url": current_url,
                    "headers": {"Host": target.hostname},
                }
            else:
                req_kwargs = request_kwargs_for(target)

            response = await client.get(**req_kwargs)

            if response.is_redirect and redirect_hops < MAX_REDIRECTS:
                location = response.headers.get("location")
                if not location:
                    break
                current_url = location
                redirect_hops += 1
            else:
                break

    return response, redirect_hops


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------

mcp = FastMCP("hivewire-co-routing")


@mcp.tool()
async def web_fetch(url: str, route_profile: RouteProfile) -> str:
    """Fetch a URL through the specified egress pool.

    SSRF guard is applied on the initial URL and on every redirect hop.
    Returns JSON with status_code, body (capped at 10 000 chars), headers,
    and routing metadata.

    scope: egress_pool + region + session_policy only.
    model_tier binding (A2) is out of scope for this demo.
    Latency and proxy reliability are out of scope — see TODOS.md.
    """
    pools = load_pools()
    pool = pools.get(route_profile.egress_pool)
    if pool is None:
        raise ValueError(
            f"Unknown egress pool {route_profile.egress_pool!r}. "
            f"Available: {sorted(pools)}"
        )

    proxy_url = None if pool.mock else pool.proxy_url

    try:
        response, redirect_hops = await _fetch_with_ssrf_guard(url, proxy_url)
    except SSRFBlockedError as exc:
        return json.dumps({"error": f"SSRF blocked: {exc}", "url": url})

    return json.dumps(
        {
            "status_code": response.status_code,
            "url": str(response.url),
            "body": response.text[:10_000],
            "headers": dict(response.headers),
            "routing": {
                "egress_pool": route_profile.egress_pool,
                "region": route_profile.region,
                "session_policy": route_profile.session_policy,
                "mock": pool.mock,
                "proxy": proxy_url or "[MOCK — direct connection, no proxy]",
                "redirect_hops": redirect_hops,
            },
        },
        default=str,
    )


if __name__ == "__main__":
    mcp.run()
