"""SSRF guard for the web_fetch tool.

Resolves a hostname exactly once, validates every resolved address, and
pins the connection to that single validated IP -- closing the DNS-rebinding
TOCTOU window where a hostname could resolve to a public IP at check time
and a private one at connect time. The original hostname is preserved for
the Host header and TLS SNI so certificate validation still works against
a connection made directly to an IP literal.

No mature, lightweight httpx SSRF-guard package exists yet to depend on
(the one candidate found, tachyon-oss/drawbridge, is alpha with a single
commit) -- this hand-rolls the same approach Prefect's internal
SSRFProtectedHTTPTransport uses: resolve via socket.getaddrinfo, reject any
disallowed resolved address, then connect to the pinned IP via httpx's
documented `extensions={"sni_hostname": ...}` mechanism.

Caller (server.py) is responsible for calling validate_fetch_url again on
every redirect hop -- this module only validates a single URL.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = {"http", "https"}


class SSRFBlockedError(ValueError):
    """Raised when a URL resolves to a disallowed address, or fails validation."""


@dataclass(frozen=True)
class SafeTarget:
    """A URL that has been validated and pinned to a single resolved IP."""

    original_url: str
    pinned_url: str
    hostname: str
    resolved_ip: str


def _is_disallowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address class that must never be reachable from this tool.

    Deliberately redundant with `is_private` rather than relying on it alone --
    the exact set of ranges `is_private` covers has shifted across Python
    versions, but `is_loopback` / `is_link_local` / `is_multicast` /
    `is_reserved` / `is_unspecified` are stable, explicit, and cheap to check.
    `is_link_local` covers 169.254.0.0/16, which includes the cloud metadata
    address 169.254.169.254.
    """
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_fetch_url(url: str) -> SafeTarget:
    """Validate a URL and pin it to a single resolved IP.

    Raises SSRFBlockedError if: the scheme isn't http/https, the URL has no
    hostname, the hostname fails to resolve, or ANY resolved address
    (a hostname can have multiple A/AAAA records) is private, loopback,
    link-local, multicast, reserved, or unspecified.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise SSRFBlockedError(f"scheme {parts.scheme!r} not allowed, only http/https")

    hostname = parts.hostname
    if not hostname:
        raise SSRFBlockedError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"could not resolve hostname {hostname!r}: {exc}") from exc

    resolved_ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        raw_ip = sockaddr[0]
        ip = ipaddress.ip_address(raw_ip)
        if _is_disallowed(ip):
            raise SSRFBlockedError(
                f"hostname {hostname!r} resolves to disallowed address {raw_ip}"
            )
        if raw_ip not in resolved_ips:
            resolved_ips.append(raw_ip)

    if not resolved_ips:
        raise SSRFBlockedError(f"hostname {hostname!r} did not resolve to any address")

    pinned_ip = resolved_ips[0]
    pinned_netloc = pinned_ip if ":" not in pinned_ip else f"[{pinned_ip}]"
    if parts.port:
        pinned_netloc += f":{parts.port}"
    pinned_url = urlunsplit((parts.scheme, pinned_netloc, parts.path, parts.query, parts.fragment))

    return SafeTarget(
        original_url=url,
        pinned_url=pinned_url,
        hostname=hostname,
        resolved_ip=pinned_ip,
    )


def request_kwargs_for(target: SafeTarget) -> dict:
    """httpx request kwargs that connect to the pinned IP while preserving
    the original Host header and TLS SNI hostname, so certificate
    validation still checks against the real hostname."""
    return {
        "url": target.pinned_url,
        "headers": {"Host": target.hostname},
        "extensions": {"sni_hostname": target.hostname},
    }
