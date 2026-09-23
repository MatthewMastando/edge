"""Keep server secrets out of logs and model context."""

from __future__ import annotations

import os
import re

_SECRET_ENV = (
    "DATABASE_URL",
    "DATABASE_ADMIN_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_ANON_KEY",
    "OPENAI_API_KEY",
    "DATABENTO_API_KEY",
    "ALPACA_API_KEY_ID",
    "ALPACA_API_SECRET_KEY",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    "TAVILY_API_KEY",
    "FRED_API_KEY",
    "EIA_API_KEY",
    "USDA_NASS_API_KEY",
    "SEC_EDGAR_USER_AGENT",
)

_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-+/=]{8,}", re.IGNORECASE)
_KEY = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")


def secrets_from_environ() -> tuple[str, ...]:
    found: list[str] = []
    for name in _SECRET_ENV:
        value = os.environ.get(name, "")
        if len(value) >= 8:
            found.append(value)
    return tuple(found)


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    redacted = _BEARER.sub("Bearer [redacted]", text)
    redacted = _KEY.sub("[redacted]", redacted)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
