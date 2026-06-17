"""Tests for ssrf_guard. socket.getaddrinfo is monkeypatched in every test
so resolution results are deterministic and don't depend on real DNS/network
(needed in sandboxed/offline CI environments too)."""

from __future__ import annotations

import socket

import pytest

from ssrf_guard import SSRFBlockedError, request_kwargs_for, validate_fetch_url


def _addrinfo(*ips: str) -> list[tuple]:
    """Build a socket.getaddrinfo()-shaped return value for the given IPs."""
    result = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        sockaddr = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        result.append((family, socket.SOCK_STREAM, 6, "", sockaddr))
    return result


def test_public_url_passes(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("93.184.216.34"))
    target = validate_fetch_url("https://example.com/path?q=1")
    assert target.hostname == "example.com"
    assert target.resolved_ip == "93.184.216.34"
    assert target.pinned_url == "https://93.184.216.34/path?q=1"


def test_private_ip_blocked(monkeypatch):
    for ip in ["10.0.0.5", "192.168.1.1", "172.16.0.1"]:
        monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, ip=ip: _addrinfo(ip))
        with pytest.raises(SSRFBlockedError, match="disallowed address"):
            validate_fetch_url("http://internal.example/")


def test_loopback_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("127.0.0.1"))
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        validate_fetch_url("http://localhost/")


def test_loopback_ipv6_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("::1"))
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        validate_fetch_url("http://localhost/")


def test_link_local_metadata_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("169.254.169.254"))
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        validate_fetch_url("http://metadata.internal/latest/meta-data/")


def test_multi_record_dns_rebinding_blocked(monkeypatch):
    """One public + one private A record: the whole hostname is untrusted."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: _addrinfo("93.184.216.34", "127.0.0.1")
    )
    with pytest.raises(SSRFBlockedError, match="disallowed address"):
        validate_fetch_url("http://attacker-controlled.example/")


def test_non_http_scheme_blocked(monkeypatch):
    with pytest.raises(SSRFBlockedError, match="scheme"):
        validate_fetch_url("file:///etc/passwd")


def test_gopher_scheme_blocked():
    with pytest.raises(SSRFBlockedError, match="scheme"):
        validate_fetch_url("gopher://example.com/")


def test_no_hostname_blocked():
    with pytest.raises(SSRFBlockedError, match="no hostname"):
        validate_fetch_url("http:///path")


def test_resolution_failure_blocked(monkeypatch):
    def _raise(host, port):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(SSRFBlockedError, match="could not resolve"):
        validate_fetch_url("http://does-not-exist.invalid/")


def test_request_kwargs_preserve_host_and_sni(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("93.184.216.34"))
    target = validate_fetch_url("https://example.com/path")
    kwargs = request_kwargs_for(target)
    assert kwargs["url"] == "https://93.184.216.34/path"
    assert kwargs["headers"]["Host"] == "example.com"
    assert kwargs["extensions"]["sni_hostname"] == "example.com"


def test_ipv6_pinned_url_uses_brackets(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: _addrinfo("2606:2800:220:1::1"))
    target = validate_fetch_url("https://example.com/path")
    assert target.pinned_url == "https://[2606:2800:220:1::1]/path"
