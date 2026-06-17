"""Tests for server.py — MCP web_fetch tool and redirect-hop SSRF re-validation.

socket.getaddrinfo is NOT monkeypatched here — instead, validate_fetch_url is
patched at the server module level so the test HTTP server (127.0.0.1) can be
reached without disabling the SSRF guard for real network calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

import server as server_module
from server import RouteProfile, SessionPolicy, _fetch_with_ssrf_guard, load_pools, web_fetch
from ssrf_guard import SSRFBlockedError, SafeTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_target(url: str, port: int, path: str = "/") -> SafeTarget:
    """SafeTarget that redirects httpx to the local pytest-httpserver instance."""
    return SafeTarget(
        original_url=url,
        pinned_url=f"http://127.0.0.1:{port}{path}",
        hostname="example.com",
        resolved_ip="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Pool registry
# ---------------------------------------------------------------------------

def test_builtin_mock_pools_used_when_no_file(tmp_path):
    pools = load_pools(path=tmp_path / "nonexistent.yaml")
    assert "mock-us-west" in pools
    assert "mock-asia" in pools
    assert "mock-eu" in pools
    assert pools["mock-us-west"].mock is True
    assert pools["mock-us-west"].proxy_url is None


def test_pools_loaded_from_yaml(tmp_path):
    yaml_file = tmp_path / "pools.yaml"
    yaml_file.write_text(
        "pools:\n"
        "  test-pool:\n"
        "    region: us-east\n"
        "    mock: false\n"
        "    proxy_url: 'http://user:pass@proxy.example:8080'\n"
    )
    pools = load_pools(path=yaml_file)
    assert "test-pool" in pools
    assert pools["test-pool"].mock is False
    assert pools["test-pool"].proxy_url == "http://user:pass@proxy.example:8080"


# ---------------------------------------------------------------------------
# web_fetch — happy path
# ---------------------------------------------------------------------------

async def test_web_fetch_returns_body(httpserver: HTTPServer, monkeypatch):
    httpserver.expect_request("/hello").respond_with_data("world", status=200)
    port = httpserver.port

    monkeypatch.setattr(
        server_module,
        "validate_fetch_url",
        lambda url: _safe_target(url, port, "/hello"),
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/hello",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    assert result["status_code"] == 200
    assert result["body"] == "world"


async def test_web_fetch_routing_metadata(httpserver: HTTPServer, monkeypatch):
    httpserver.expect_request("/").respond_with_data("ok", status=200)
    port = httpserver.port

    monkeypatch.setattr(
        server_module,
        "validate_fetch_url",
        lambda url: _safe_target(url, port),
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/",
            RouteProfile(
                egress_pool="mock-us-west",
                region="us-west",
                session_policy=SessionPolicy.sticky,
            ),
        )
    )

    routing = result["routing"]
    assert routing["egress_pool"] == "mock-us-west"
    assert routing["region"] == "us-west"
    assert routing["session_policy"] == "sticky"
    assert routing["mock"] is True
    assert "[MOCK" in routing["proxy"]
    assert routing["redirect_hops"] == 0


async def test_web_fetch_unknown_pool_raises():
    with pytest.raises(ValueError, match="Unknown egress pool"):
        await web_fetch(
            "https://example.com/",
            RouteProfile(egress_pool="does-not-exist", region="us-west"),
        )


async def test_web_fetch_body_capped_at_10k(httpserver: HTTPServer, monkeypatch):
    big_body = "x" * 20_000
    httpserver.expect_request("/big").respond_with_data(big_body, status=200)
    port = httpserver.port

    monkeypatch.setattr(
        server_module,
        "validate_fetch_url",
        lambda url: _safe_target(url, port, "/big"),
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/big",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    assert len(result["body"]) == 10_000


# ---------------------------------------------------------------------------
# Redirect-hop SSRF re-validation
# ---------------------------------------------------------------------------

async def test_redirect_to_private_ip_is_blocked(httpserver: HTTPServer, monkeypatch):
    """Redirect to a link-local/private URL must be blocked on the second hop."""
    httpserver.expect_request("/start").respond_with_data(
        "",
        status=302,
        headers={"Location": "http://169.254.169.254/meta-data/"},
    )
    port = httpserver.port

    validation_calls: list[str] = []

    def _fake_validate(url: str) -> SafeTarget:
        validation_calls.append(url)
        if "169.254.169.254" in url:
            raise SSRFBlockedError(f"hostname resolves to disallowed address 169.254.169.254")
        return _safe_target(url, port, "/start")

    monkeypatch.setattr(server_module, "validate_fetch_url", _fake_validate)

    result = json.loads(
        await web_fetch(
            "https://example.com/start",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    # validate_fetch_url called twice: initial URL + redirect Location
    assert len(validation_calls) == 2
    assert "169.254.169.254" in validation_calls[1]
    assert "error" in result
    assert "SSRF blocked" in result["error"]


async def test_safe_redirect_is_followed(httpserver: HTTPServer, monkeypatch):
    """A redirect to a safe URL must be followed and return the final body."""
    httpserver.expect_request("/start").respond_with_data(
        "",
        status=302,
        headers={"Location": "https://example.com/final"},
    )
    httpserver.expect_request("/final").respond_with_data("final content", status=200)
    port = httpserver.port

    def _fake_validate(url: str) -> SafeTarget:
        path = "/final" if "/final" in url else "/start"
        return _safe_target(url, port, path)

    monkeypatch.setattr(server_module, "validate_fetch_url", _fake_validate)

    result = json.loads(
        await web_fetch(
            "https://example.com/start",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    assert result["status_code"] == 200
    assert result["body"] == "final content"
    assert result["routing"]["redirect_hops"] == 1


async def test_initial_url_ssrf_blocked_returns_error_dict(monkeypatch):
    """SSRF block on the initial URL returns an error JSON, not an exception."""

    def _blocked(url: str) -> SafeTarget:
        raise SSRFBlockedError("disallowed address 10.0.0.1")

    monkeypatch.setattr(server_module, "validate_fetch_url", _blocked)

    result = json.loads(
        await web_fetch(
            "http://10.0.0.1/secret",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    assert "error" in result
    assert "SSRF blocked" in result["error"]
    assert result["url"] == "http://10.0.0.1/secret"


async def test_multiple_safe_redirects_all_revalidated(httpserver: HTTPServer, monkeypatch):
    """Each hop in a multi-redirect chain calls validate_fetch_url."""
    httpserver.expect_request("/hop1").respond_with_data(
        "", status=302, headers={"Location": "https://example.com/hop2"}
    )
    httpserver.expect_request("/hop2").respond_with_data(
        "", status=302, headers={"Location": "https://example.com/final"}
    )
    httpserver.expect_request("/final").respond_with_data("done", status=200)
    port = httpserver.port

    validation_calls: list[str] = []

    def _fake_validate(url: str) -> SafeTarget:
        validation_calls.append(url)
        for seg in ("/hop1", "/hop2", "/final"):
            if seg in url:
                return _safe_target(url, port, seg)
        return _safe_target(url, port, "/hop1")

    monkeypatch.setattr(server_module, "validate_fetch_url", _fake_validate)

    result = json.loads(
        await web_fetch(
            "https://example.com/hop1",
            RouteProfile(egress_pool="mock-us-west", region="us-west"),
        )
    )

    assert result["status_code"] == 200
    assert result["body"] == "done"
    assert result["routing"]["redirect_hops"] == 2
    # validate_fetch_url called once per URL: hop1, hop2, final
    assert len(validation_calls) == 3


# ---------------------------------------------------------------------------
# Session policy
# ---------------------------------------------------------------------------

async def test_rotating_session_policy_in_metadata(httpserver: HTTPServer, monkeypatch):
    httpserver.expect_request("/").respond_with_data("ok", status=200)
    port = httpserver.port
    monkeypatch.setattr(
        server_module, "validate_fetch_url", lambda url: _safe_target(url, port)
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/",
            RouteProfile(egress_pool="mock-us-west", region="us-west", session_policy="rotating"),
        )
    )
    assert result["routing"]["session_policy"] == "rotating"


async def test_sticky_session_policy_in_metadata(httpserver: HTTPServer, monkeypatch):
    httpserver.expect_request("/").respond_with_data("ok", status=200)
    port = httpserver.port
    monkeypatch.setattr(
        server_module, "validate_fetch_url", lambda url: _safe_target(url, port)
    )

    result = json.loads(
        await web_fetch(
            "https://example.com/",
            RouteProfile(egress_pool="mock-us-west", region="us-west", session_policy="sticky"),
        )
    )
    assert result["routing"]["session_policy"] == "sticky"
