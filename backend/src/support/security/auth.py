"""Password hashing (stdlib scrypt) and JWT access tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

Role = Literal["customer", "agent"]

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. `customer_id` is set only for customer accounts."""

    user_id: str
    role: Role
    customer_id: str | None
    display_name: str

    @property
    def is_agent(self) -> bool:
        return self.role == "agent"


class TokenError(Exception):
    pass


def create_access_token(p: Principal, secret: str, algorithm: str, ttl_minutes: int) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": p.user_id,
        "role": p.role,
        "cid": p.customer_id,
        "name": p.display_name,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(claims, secret, algorithm=algorithm)


def decode_access_token(token: str, secret: str, algorithm: str) -> Principal:
    try:
        c = jwt.decode(token, secret, algorithms=[algorithm], options={"require": ["exp", "sub", "role"]})
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    if c["role"] not in ("customer", "agent"):
        raise TokenError("invalid role")
    return Principal(user_id=c["sub"], role=c["role"], customer_id=c.get("cid"), display_name=c.get("name", ""))
