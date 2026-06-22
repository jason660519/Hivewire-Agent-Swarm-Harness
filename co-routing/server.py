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
import re
import secrets
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, model_validator

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
    # A2 field — which model tier this profile binds to. Unused by web_fetch
    # (egress-only); consumed by litellm_corouting.py. See design.md §A2.
    model_tier: str | None = None


# ---------------------------------------------------------------------------
# Pool registry
# ---------------------------------------------------------------------------

class PoolConfig(BaseModel):
    """An egress pool.

    Three flavors, in resolution order:
    - ``mock: true``           → direct connection, no proxy (offline demo).
    - ``proxy_template`` set    → vendor adapter. ``{region}`` and
      ``{session_id}`` are substituted per request so one pool serves every
      region/session the caller asks for. This is how "any proxy vendor is a
      config change" holds: most residential vendors encode region + session
      into the proxy username, e.g.
      ``http://user-country-{region}-session-{session_id}:pass@gw.vendor.io:8080``.
    - ``proxy_url`` set         → a single fixed upstream proxy (no per-request
      variation). Kept for backward compatibility.

    ``region`` is an optional label only; the region that actually drives the
    connection is ``RouteProfile.region`` (substituted into the template).
    """

    region: str | None = None
    mock: bool = False
    proxy_url: str | None = None
    proxy_template: str | None = None

    @model_validator(mode="after")
    def _check_egress_source(self) -> "PoolConfig":
        if not self.mock and not self.proxy_url and not self.proxy_template:
            raise ValueError(
                "non-mock pool must set either proxy_url or proxy_template"
            )
        return self


def _builtin_mock_pools() -> dict[str, PoolConfig]:
    """Built-in mock pools — direct connections, clearly labeled in metadata."""
    return {
        "mock-us-west": PoolConfig(region="us-west", mock=True),
        "mock-asia": PoolConfig(region="asia", mock=True),
        "mock-eu": PoolConfig(region="eu", mock=True),
    }


_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """Load .env into os.environ (without overriding real env vars) so pool
    config can reference ${VARS} whose secrets live only in .env. Looks in cwd
    and at the repo root (server.py's grandparent dir)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def _expand_env(value: str | None) -> str | None:
    """Expand ${VAR} from the environment (loading .env on first need). Keeps
    secrets out of pools.yaml — it holds var names, .env holds the values."""
    if not value or "$" not in value:
        return value
    _load_dotenv_once()
    expanded = os.path.expandvars(value)
    missing = re.findall(r"\$\{([^}]+)\}", expanded)
    if missing:
        raise ValueError(
            f"pool config references unset env var(s): {missing}. Set them in .env"
        )
    return expanded


def load_pools(path: Path = _POOLS_FILE) -> dict[str, PoolConfig]:
    """Load pools with their config verbatim. ${VAR} references are NOT expanded
    here — expansion is lazy (resolve_proxy_url), so an unset env var only errors
    for the pool that's actually used, not every pool in the file."""
    if not path.exists():
        return _builtin_mock_pools()
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {name: PoolConfig(**cfg) for name, cfg in raw.get("pools", {}).items()}


# ---------------------------------------------------------------------------
# Vendor adapter: turn a RouteProfile into a concrete upstream proxy URL
# ---------------------------------------------------------------------------

# Sticky session ids, keyed by (pool, region), stable for this process's
# lifetime — so session_policy=sticky reuses the same upstream IP across calls,
# which is exactly "same IP for the session's duration" from design.md §Target.
_STICKY_SESSIONS: dict[tuple[str, str], str] = {}


def _session_id_for(pool_name: str, region: str, policy: SessionPolicy) -> str:
    """A short session token. ``sticky`` returns a stable id per (pool, region);
    ``rotating`` returns a fresh id every call so the vendor hands out a new IP."""
    if policy is SessionPolicy.sticky:
        return _STICKY_SESSIONS.setdefault((pool_name, region), secrets.token_hex(6))
    return secrets.token_hex(6)


def _render_template(template: str, *, region: str, session_id: str) -> str:
    """Substitute placeholders without str.format, so literal ``{`` / ``}`` in
    a proxy password can't blow up or be interpreted as a field."""
    return template.replace("{region}", region).replace("{session_id}", session_id)


def resolve_proxy_url(
    pool: PoolConfig, route: RouteProfile, session_id: str
) -> str | None:
    """The upstream proxy URL for this request, or None for a direct (mock)
    connection. ``proxy_template`` takes precedence over ``proxy_url``."""
    if pool.mock:
        return None
    if pool.proxy_template:
        rendered = _render_template(
            pool.proxy_template, region=route.region, session_id=session_id
        )
        return _expand_env(rendered)
    return _expand_env(pool.proxy_url)


def _mask_proxy(proxy_url: str | None) -> str:
    """Strip credentials before echoing a proxy into response metadata —
    a templated vendor URL embeds username:password in the userinfo."""
    if not proxy_url:
        return "[MOCK — direct connection, no proxy]"
    parts = urlsplit(proxy_url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, "", "", "")) or "[unparseable proxy]"


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

    session_id = _session_id_for(
        route_profile.egress_pool, route_profile.region, route_profile.session_policy
    )
    proxy_url = resolve_proxy_url(pool, route_profile, session_id)

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
                "session_id": session_id,
                "mock": pool.mock,
                "proxy": _mask_proxy(proxy_url),
                "redirect_hops": redirect_hops,
            },
        },
        default=str,
    )


if __name__ == "__main__":
    mcp.run()
