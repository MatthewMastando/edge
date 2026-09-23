"""Build research services. An empty environment returns None so the fixture path is unchanged."""

from __future__ import annotations

from typing import Literal

from trading_core.domain.common import DomainModel
from trading_core.http_client import HttpxTransport, Transport
from trading_core.research.fetch import SafeFetcher
from trading_core.research.official import (
    CalendarSource,
    EiaSource,
    FredSource,
    NassSource,
    SecSource,
)
from trading_core.research.policy import DomainPolicy
from trading_core.research.search import FixtureSearchProvider, TavilySearchProvider
from trading_core.research.services import ResearchServices
from trading_core.research.ssrf import Resolver, default_resolver

SearchChoice = Literal["fixture", "tavily"]


class ResearchConfig(DomainModel):
    search_provider: SearchChoice = "fixture"
    tavily_api_key: str = ""
    fred_api_key: str = ""
    eia_api_key: str = ""
    nass_api_key: str = ""
    sec_user_agent: str = ""
    domain_allow: tuple[str, ...] = ()
    domain_deny: tuple[str, ...] = ()
    max_bytes: int = 1_000_000
    timeout_seconds: float = 10.0

    @property
    def is_fixture_only(self) -> bool:
        return (
            self.search_provider == "fixture"
            and not self.tavily_api_key
            and not self.fred_api_key
            and not self.eia_api_key
            and not self.nass_api_key
            and not self.sec_user_agent
            and not self.domain_allow
            and not self.domain_deny
        )


def research_config_from_values(
    *,
    search_provider: str = "fixture",
    tavily_api_key: str = "",
    fred_api_key: str = "",
    eia_api_key: str = "",
    nass_api_key: str = "",
    sec_user_agent: str = "",
    domain_allow: str = "",
    domain_deny: str = "",
    max_bytes: int = 1_000_000,
    timeout_seconds: float = 10.0,
) -> ResearchConfig:
    choice: SearchChoice = "tavily" if search_provider == "tavily" else "fixture"
    if search_provider not in {"", "fixture", "tavily"}:
        msg = f"SEARCH_PROVIDER must be fixture or tavily, got {search_provider!r}"
        raise ValueError(msg)
    return ResearchConfig(
        search_provider=choice,
        tavily_api_key=tavily_api_key,
        fred_api_key=fred_api_key,
        eia_api_key=eia_api_key,
        nass_api_key=nass_api_key,
        sec_user_agent=sec_user_agent,
        domain_allow=_split(domain_allow),
        domain_deny=_split(domain_deny),
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
    )


def build_research_services(
    config: ResearchConfig,
    *,
    transport: Transport | None = None,
    resolver: Resolver = default_resolver,
) -> ResearchServices | None:
    if config.is_fixture_only:
        return None
    client = transport or HttpxTransport()
    policy = DomainPolicy(config.domain_allow, config.domain_deny)
    search: FixtureSearchProvider | TavilySearchProvider
    if config.search_provider == "tavily":
        search = TavilySearchProvider(
            api_key=config.tavily_api_key, transport=client, policy=policy
        )
    else:
        search = FixtureSearchProvider()
    fetcher = SafeFetcher(
        transport=client,
        policy=policy,
        max_bytes=config.max_bytes,
        timeout_seconds=config.timeout_seconds,
        resolver=resolver,
    )
    return ResearchServices(
        search=search,
        fred=FredSource(api_key=config.fred_api_key, transport=client),
        eia=EiaSource(api_key=config.eia_api_key, transport=client),
        nass=NassSource(api_key=config.nass_api_key, transport=client),
        sec=SecSource(user_agent=config.sec_user_agent, transport=client),
        calendars=CalendarSource(fetcher=fetcher),
        fetcher=fetcher,
    )


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())
