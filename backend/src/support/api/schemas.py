"""HTTP request/response models (the API contract; mirrored in frontend/src/api/types.ts)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from support.domain.enums import TicketStatus


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    role: Literal["customer", "agent"]
    display_name: str
    customer_id: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut


class DemoAccount(BaseModel):
    email: str
    password: str
    role: Literal["customer", "agent"]
    display_name: str
    blurb: str


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class Source(BaseModel):
    source: str
    title: str
    url: str


class TranscriptMessage(BaseModel):
    id: str | None
    role: Literal["customer", "assistant"]
    agent: str | None = None
    content: str
    sources: list[Source] = []


class TurnResult(BaseModel):
    message: TranscriptMessage
    active_agent: str | None
    events: list[dict[str, Any]]


class TicketUpdateIn(BaseModel):
    status: TicketStatus


class RefundDecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)
