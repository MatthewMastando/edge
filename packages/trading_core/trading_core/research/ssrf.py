"""Reject private, loopback, link-local, and other non-public addresses before a fetch."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)
_BLOCKED_NAMES = {"localhost", "metadata.google.internal", "metadata.internal"}


class AddressBlockedError(ValueError):
    def __init__(self, host: str, reason: str) -> None:
        self.host = host
        self.reason = reason
        super().__init__(f"{host} blocked: {reason}")


Resolver = Callable[[str, int], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]


def default_resolver(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        address = info[4][0]
        if isinstance(address, str):
            found.append(ipaddress.ip_address(address.split("%")[0]))
    return found


def check_url(url: str, resolver: Resolver = default_resolver) -> str:
    """Return the hostname when every resolved address is public. Otherwise raise."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AddressBlockedError(url, "only http and https are allowed")
    if parsed.username or parsed.password:
        raise AddressBlockedError(parsed.hostname or url, "credentials in the URL are not allowed")
    host = parsed.hostname
    if host is None or host == "":
        raise AddressBlockedError(url, "missing host")
    if host.lower().rstrip(".") in _BLOCKED_NAMES:
        raise AddressBlockedError(host, "blocked hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = resolver(host, port)
    else:
        addresses = [literal]
    if not addresses:
        raise AddressBlockedError(host, "did not resolve")
    for address in addresses:
        if _blocked(address):
            raise AddressBlockedError(host, f"non-public address {address}")
    return host


def _blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _blocked(address.ipv4_mapped)
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True
    if address.version != 4:
        return False
    return any(address in network for network in _BLOCKED_NETWORKS)
