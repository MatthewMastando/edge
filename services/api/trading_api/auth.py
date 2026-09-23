"""Authentication seam. Stage 1B verifies Supabase JWTs here; Stage 0 only defines the contract.

In fixture mode with no JWT secret configured the API serves a single local development user so
the web app and tests work against `uvicorn` bound to localhost. Any other configuration refuses
requests until verification is implemented, so nothing can be exposed unauthenticated by accident.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

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


def current_user(request: Request, settings: SettingsDep) -> CurrentUser:
    if settings.mode == "fixture" and not settings.supabase_jwt_secret:
        return CurrentUser(id=LOCAL_DEV_USER_ID, email=None, is_local_dev=True)
    if request.headers.get("authorization"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="JWT verification is implemented in Stage 1B",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


UserDep = Annotated[CurrentUser, Depends(current_user)]
