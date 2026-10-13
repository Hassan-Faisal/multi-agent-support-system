from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from support.api.container import Container
from support.db.session import unit_of_work
from support.security.auth import Principal, TokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(c: ContainerDep) -> AsyncIterator[AsyncSession]:
    """One transaction per request: committed if the handler returns, rolled back on error."""
    async with unit_of_work(c.sessions) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_principal(
    c: ContainerDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        p = decode_access_token(
            creds.credentials, c.settings.jwt_secret.get_secret_value(), c.settings.jwt_algorithm
        )
    except TokenError as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from e
    structlog.contextvars.bind_contextvars(user_id=p.user_id, role=p.role)
    return p


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_customer(p: PrincipalDep) -> Principal:
    if p.role != "customer" or not p.customer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer account required")
    return p


def require_agent(p: PrincipalDep) -> Principal:
    if not p.is_agent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Support staff only")
    return p


CustomerDep = Annotated[Principal, Depends(require_customer)]
AgentDep = Annotated[Principal, Depends(require_agent)]


async def rate_limited(c: ContainerDep, p: PrincipalDep) -> None:
    allowed, retry_after = await c.limiter.hit(f"chat:{p.user_id}")
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many messages, slow down a little",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
