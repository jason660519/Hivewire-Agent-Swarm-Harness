"""Tests for the vendor adapter layer — proxy_template rendering, session-id
policy (sticky stable / rotating fresh), proxy resolution precedence, and
credential masking in response metadata.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import server as server_module
from server import (
    PoolConfig,
    RouteProfile,
    SessionPolicy,
    _mask_proxy,
    _render_template,
    _session_id_for,
    load_pools,
    resolve_proxy_url,
    web_fetch,
)
from ssrf_guard import SafeTarget


@pytest.fixture(autouse=True)
def _clear_sticky():
    server_module._STICKY_SESSIONS.clear()
    yield
    server_module._STICKY_SESSIONS.clear()


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def test_render_substitutes_region_and_session():
    out = _render_template(
        "http://u-country-{region}-session-{session_id}:p@gw:8080",
        region="us",
        session_id="abc123",
    )
    assert out == "http://u-country-us-session-abc123:p@gw:8080"


def test_render_leaves_literal_braces_in_password_untouched():
    # A password containing { } must not be treated as a placeholder.
    out = _render_template(
        "http://user:p{ass}word@gw:8080", region="us", session_id="x"
    )
    assert out == "http://user:p{ass}word@gw:8080"


# ---------------------------------------------------------------------------
# Session-id policy
# ---------------------------------------------------------------------------

def test_sticky_session_id_stable_across_calls():
    a = _session_id_for("pool-a", "us", SessionPolicy.sticky)
    b = _session_id_for("pool-a", "us", SessionPolicy.sticky)
    assert a == b


def test_sticky_session_id_differs_per_pool_and_region():
    base = _session_id_for("pool-a", "us", SessionPolicy.sticky)
    other_region = _session_id_for("pool-a", "gb", SessionPolicy.sticky)
    other_pool = _session_id_for("pool-b", "us", SessionPolicy.sticky)
    assert base != other_region
    assert base != other_pool


def test_rotating_session_id_fresh_each_call():
    a = _session_id_for("pool-a", "us", SessionPolicy.rotating)
    b = _session_id_for("pool-a", "us", SessionPolicy.rotating)
    assert a != b


# ---------------------------------------------------------------------------
# Proxy resolution precedence
# ---------------------------------------------------------------------------

def test_mock_pool_resolves_to_no_proxy():
    pool = PoolConfig(region="us", mock=True)
    route = RouteProfile(egress_pool="p", region="us")
    assert resolve_proxy_url(pool, route, "sid") is None


def test_template_takes_precedence_over_proxy_url():
    pool = PoolConfig(
        mock=False,
        proxy_url="http://fixed:pw@gw:8080",
        proxy_template="http://u-{region}-{session_id}:pw@gw:8080",
    )
    route = RouteProfile(egress_pool="p", region="gb")
    assert resolve_proxy_url(pool, route, "sid9") == "http://u-gb-sid9:pw@gw:8080"


def test_fixed_proxy_url_used_when_no_template():
    pool = PoolConfig(mock=False, proxy_url="http://fixed:pw@gw:8080")
    route = RouteProfile(egress_pool="p", region="us")
    assert resolve_proxy_url(pool, route, "sid") == "http://fixed:pw@gw:8080"


def test_non_mock_pool_without_egress_source_rejected():
    with pytest.raises(ValidationError, match="proxy_url or proxy_template"):
        PoolConfig(mock=False)


def test_resolve_expands_env_var(monkeypatch):
    # Secret lives in the env (i.e. .env); pools.yaml only names the var.
    monkeypatch.setenv("PC_TEST_URL", "http://u:p@gw.test:8080")
    pool = PoolConfig(mock=False, proxy_url="${PC_TEST_URL}")
    route = RouteProfile(egress_pool="v", region="us")
    assert resolve_proxy_url(pool, route, "sid") == "http://u:p@gw.test:8080"


def test_resolve_unset_env_var_raises(monkeypatch):
    monkeypatch.delenv("PC_DEFINITELY_UNSET_URL", raising=False)
    pool = PoolConfig(mock=False, proxy_url="${PC_DEFINITELY_UNSET_URL}")
    route = RouteProfile(egress_pool="v", region="us")
    with pytest.raises(ValueError, match="unset env var"):
        resolve_proxy_url(pool, route, "sid")


def test_unused_env_pool_does_not_break_load(tmp_path, monkeypatch):
    # An unset ${VAR} in one pool must not stop other pools loading/resolving.
    monkeypatch.delenv("PC_UNSET", raising=False)
    yaml_file = tmp_path / "pools.yaml"
    yaml_file.write_text(
        "pools:\n"
        "  mock-x:\n    region: us\n    mock: true\n"
        "  needs-env:\n    mock: false\n    proxy_url: '${PC_UNSET}'\n"
    )
    pools = load_pools(path=yaml_file)  # must not raise
    assert "mock-x" in pools and "needs-env" in pools
    # the mock pool resolves fine even though needs-env's var is unset
    assert resolve_proxy_url(pools["mock-x"], RouteProfile(egress_pool="mock-x", region="us"), "s") is None


def test_template_pool_loaded_from_yaml(tmp_path):
    yaml_file = tmp_path / "pools.yaml"
    yaml_file.write_text(
        "pools:\n"
        "  vend:\n"
        "    mock: false\n"
        "    proxy_template: 'http://u-{region}-{session_id}:p@gw:8080'\n"
    )
    pools = load_pools(path=yaml_file)
    assert pools["vend"].proxy_template == "http://u-{region}-{session_id}:p@gw:8080"


# ---------------------------------------------------------------------------
# Credential masking
# ---------------------------------------------------------------------------

def test_mask_strips_userinfo():
    masked = _mask_proxy("http://user-country-us-session-abc:secret@gw.vendor.io:8080")
    assert masked == "http://gw.vendor.io:8080"
    assert "secret" not in masked
    assert "user-country" not in masked


def test_mask_mock_is_labeled():
    assert "[MOCK" in _mask_proxy(None)


# ---------------------------------------------------------------------------
# web_fetch metadata surfaces session_id and never leaks credentials
# ---------------------------------------------------------------------------

async def test_web_fetch_metadata_includes_session_id(httpserver, monkeypatch):
    httpserver.expect_request("/").respond_with_data("ok", status=200)
    port = httpserver.port
    monkeypatch.setattr(
        server_module,
        "validate_fetch_url",
        lambda url: SafeTarget(url, f"http://127.0.0.1:{port}/", "example.com", "127.0.0.1"),
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/",
            RouteProfile(egress_pool="mock-us-west", region="us-west", session_policy="sticky"),
        )
    )
    assert result["routing"]["session_id"]
    assert "[MOCK" in result["routing"]["proxy"]
