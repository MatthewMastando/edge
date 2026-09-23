"""Reject private, loopback, link-local, and other non-public addresses before a fetch.

Obfuscated IPv4 forms (decimal, hex, octal, and short dotted forms) are decoded here.
They are not handed to DNS, because libc and HTTP clients do not agree on those forms.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)
_BLOCKED_NAMES = {"localhost", "metadata.google.internal", "metadata.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local")
_IP_PART = re.compile(r"^(?:0x[0-9a-f]+|\d+)$", re.IGNORECASE)


class AddressBlockedError(ValueError):
    def __init__(self, host: str, reason: str) -> None:
        self.host = host
        self.reason = reason
        super().__init__(f"{host} blocked: {reason}")


Resolver = Callable[[str, int], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]


@dataclass(frozen=True)
class PreparedUrl:
    """A URL that passed scheme and hostname checks. Names are not resolved yet."""

    host: str
    port: int
    literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None


def default_resolver(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        address = info[4][0]
        if isinstance(address, str):
            found.append(ipaddress.ip_address(address.split("%")[0]))
    return found


def inspect_url(url: str) -> PreparedUrl:
    """Validate the URL without DNS. Private literals, including obfuscated ones, raise."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AddressBlockedError(url, "only http and https are allowed")
    if parsed.username or parsed.password:
        raise AddressBlockedError(parsed.hostname or url, "credentials in the URL are not allowed")
    host = parsed.hostname
    if host is None or host == "":
        raise AddressBlockedError(url, "missing host")
    normalized = host.lower().rstrip(".")
    if normalized in _BLOCKED_NAMES or normalized.endswith(_BLOCKED_SUFFIXES):
        raise AddressBlockedError(host, "blocked hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    literal = _literal_address(host)
    if literal is not None and _blocked(literal):
        raise AddressBlockedError(host, f"non-public address {literal}")
    return PreparedUrl(host=host, port=port, literal=literal)


def check_url(url: str, resolver: Resolver = default_resolver) -> str:
    """Return the hostname when every resolved address is public. Otherwise raise."""
    prepared = inspect_url(url)
    if prepared.literal is not None:
        return prepared.host
    require_public(prepared.host, resolver(prepared.host, prepared.port))
    return prepared.host


def static_block_reason(url: str) -> str | None:
    """Reject non-public URL literals without DNS. Names are checked later, at fetch time."""
    try:
        inspect_url(url)
    except AddressBlockedError as exc:
        return str(exc)
    return None


def require_public(
    host: str, addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address]
) -> None:
    if not addresses:
        raise AddressBlockedError(host, "did not resolve")
    for address in addresses:
        if _blocked(address):
            raise AddressBlockedError(host, f"non-public address {address}")


def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return _ipv4_encoding(host)
    except ValueError as exc:
        raise AddressBlockedError(host, "malformed address") from exc


def _ipv4_encoding(host: str) -> ipaddress.IPv4Address | None:
    """Decode inet_aton forms. None means this is a hostname, not an address encoding."""
    parts = host.split(".")
    if len(parts) > 4 or not all(_IP_PART.fullmatch(part) for part in parts):
        return None
    return _assemble_ipv4([_part_value(part) for part in parts])


def _part_value(part: str) -> int:
    lowered = part.lower()
    if lowered.startswith("0x"):
        return int(lowered, 16)
    if lowered.startswith("0") and len(lowered) > 1:
        if any(char > "7" for char in lowered):
            msg = "invalid octal"
            raise ValueError(msg)
        return int(lowered, 8)
    return int(lowered, 10)


def _assemble_ipv4(numbers: list[int]) -> ipaddress.IPv4Address:
    if len(numbers) == 1:
        if numbers[0] > 0xFFFFFFFF:
            msg = "out of range"
            raise ValueError(msg)
        return ipaddress.IPv4Address(numbers[0])
    last_bits = 32 - (8 * (len(numbers) - 1))
    if any(number >= 256 for number in numbers[:-1]) or numbers[-1] >= 1 << last_bits:
        msg = "out of range"
        raise ValueError(msg)
    value = numbers[-1]
    shift = last_bits
    for number in reversed(numbers[:-1]):
        value |= number << shift
        shift += 8
    return ipaddress.IPv4Address(value)


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
