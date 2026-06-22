"""Tests for A2 — model-tier x egress co-routing config.

These need only httpx (core dep); litellm is not imported, so they run in the
default dev environment without the optional [litellm] extra.
"""
from __future__ import annotations

import httpx
import pytest

from litellm_corouting import (
    TierBinding,
    build_egress_client,
    build_model_list,
    egress_async_client,
)
from server import PoolConfig, RouteProfile


def test_build_model_list_maps_tier_to_model():
    bindings = [
        TierBinding(model_tier="smart", model="anthropic/claude-opus-4-8", egress_pool="p"),
        TierBinding(model_tier="cheap", model="openai/gpt-4o-mini", egress_pool="p"),
    ]
    model_list = build_model_list(bindings)

    assert model_list == [
        {"model_name": "smart", "litellm_params": {"model": "anthropic/claude-opus-4-8"}},
        {"model_name": "cheap", "litellm_params": {"model": "openai/gpt-4o-mini"}},
    ]


def _has_all_mount(client: httpx.AsyncClient) -> bool:
    return any(pattern.pattern == "all://" for pattern in client._mounts)


async def test_egress_client_direct_when_no_proxy():
    # A direct client carries no explicit mounts (catches httpx API drift too).
    client = egress_async_client(None)
    assert isinstance(client, httpx.AsyncClient)
    assert client._mounts == {}
    await client.aclose()


async def test_egress_client_mounts_proxy_transport():
    client = egress_async_client("http://user:pass@gw.vendor.io:8080")
    # An explicit "all://" mount means every request routes through the proxy
    # transport we built.
    assert _has_all_mount(client)
    await client.aclose()


async def test_build_egress_client_uses_template_proxy():
    pool = PoolConfig(
        mock=False,
        proxy_template="http://u-country-{region}-session-{session_id}:pw@gw:8080",
    )
    route = RouteProfile(egress_pool="vend", region="gb", model_tier="smart")
    client = build_egress_client(pool, route)
    assert _has_all_mount(client)
    await client.aclose()


async def test_build_egress_client_mock_pool_is_direct():
    pool = PoolConfig(region="us", mock=True)
    route = RouteProfile(egress_pool="mock", region="us", model_tier="smart")
    client = build_egress_client(pool, route)
    assert isinstance(client, httpx.AsyncClient)
    await client.aclose()


def test_route_profile_accepts_model_tier():
    route = RouteProfile(egress_pool="p", region="us", model_tier="smart")
    assert route.model_tier == "smart"
    # still optional
    assert RouteProfile(egress_pool="p", region="us").model_tier is None
