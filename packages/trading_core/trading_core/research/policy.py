"""Domain allow and deny lists. Private addresses are rejected separately by the fetcher."""

from __future__ import annotations


class DomainPolicy:
    def __init__(self, allow: tuple[str, ...] = (), deny: tuple[str, ...] = ()) -> None:
        self.allow = tuple(_host(item) for item in allow if item.strip())
        self.deny = tuple(_host(item) for item in deny if item.strip())

    def permits(self, host: str) -> bool:
        name = _host(host)
        if any(_matches(name, denied) for denied in self.deny):
            return False
        if not self.allow:
            return True
        return any(_matches(name, allowed) for allowed in self.allow)

    def refusal(self, host: str) -> str | None:
        if self.permits(host):
            return None
        return f"host {host} is outside the domain allow/deny policy"


def _host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def _matches(host: str, rule: str) -> bool:
    return host == rule or host.endswith("." + rule)
