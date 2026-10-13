from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from support.api.deps import ContainerDep, PrincipalDep, SessionDep
from support.api.schemas import DemoAccount, LoginIn, TokenOut, UserOut
from support.db.models import User
from support.db.seed import DEMO_PASSWORD
from support.security.auth import Principal, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Equalizes timing between "no such user" and "wrong password".
_DUMMY_HASH = "scrypt$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def _user_out(p: Principal) -> UserOut:
    return UserOut(id=p.user_id, role=p.role, display_name=p.display_name, customer_id=p.customer_id)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep, c: ContainerDep) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(body.password, user.password_hash if user else _DUMMY_HASH) or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    p = Principal(
        user_id=str(user.id),
        role=user.role.value,
        customer_id=user.customer_id,
        display_name=user.display_name,
    )
    s = c.settings
    token = create_access_token(p, s.jwt_secret.get_secret_value(), s.jwt_algorithm, s.jwt_ttl_minutes)
    return TokenOut(access_token=token, expires_in=s.jwt_ttl_minutes * 60, user=_user_out(p))


@router.get("/me", response_model=UserOut)
async def me(p: PrincipalDep) -> UserOut:
    return _user_out(p)


@router.get("/demo-accounts", response_model=list[DemoAccount])
async def demo_accounts(c: ContainerDep) -> list[DemoAccount]:
    """Seeded logins for the demo login screen. Disabled unless explicitly enabled."""
    if not c.settings.enable_demo_accounts or c.settings.env == "prod":
        return []
    return [
        DemoAccount(
            email="ayesha@example.com",
            password=DEMO_PASSWORD,
            role="customer",
            display_name="Ayesha Khan",
            blurb="Pro plan. Has a duplicate charge and headphones on the way.",
        ),
        DemoAccount(
            email="marcus@example.com",
            password=DEMO_PASSWORD,
            role="customer",
            display_name="Marcus Lee",
            blurb="Basic plan. Has an overdue invoice and an order past the return window.",
        ),
        DemoAccount(
            email="sofia@example.com",
            password=DEMO_PASSWORD,
            role="customer",
            display_name="Sofia Rossi",
            blurb="Enterprise plan. Waiting on a delayed $1,499 desk order.",
        ),
        DemoAccount(
            email="agent@nimbus.example",
            password=DEMO_PASSWORD,
            role="agent",
            display_name="Jordan (Support)",
            blurb="Support staff. Approves large refunds and works the ticket queue.",
        ),
    ]
