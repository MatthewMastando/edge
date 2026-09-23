"""Authentication. Fixture mode with no JWT secret uses one local development user.

Live mode verifies a Supabase HS256 JWT. The secret stays in server settings and is never
written to logs or model context.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import Field

from trading_api.dependencies import SettingsDep
from trading_core.domain.common import DomainModel

LOCAL_DEV_USER_ID = UUID("00000000-0000-4000-8000-000000000001")


class CurrentUser(DomainModel):
    id: UUID
    email: str | None = None
    is_local_dev: bool = Field(
        default=False, description="True when no JWT was verified (fixture mode on localhost)."
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _user_from_jwt(token: str, secret: str) -> CurrentUser:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "require": ["sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        ) from exc
    email = payload.get("email")
    return CurrentUser(
        id=user_id,
        email=email if isinstance(email, str) else None,
        is_local_dev=False,
    )


def current_user(request: Request, settings: SettingsDep) -> CurrentUser:
    if settings.mode == "fixture" and not settings.supabase_jwt_secret:
        return CurrentUser(id=LOCAL_DEV_USER_ID, email=None, is_local_dev=True)
    token = _bearer(request)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="JWT secret is not configured",
        )
    return _user_from_jwt(token, settings.supabase_jwt_secret)


UserDep = Annotated[CurrentUser, Depends(current_user)]
