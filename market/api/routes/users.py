"""
users.py — User account and portfolio endpoints.

Routes
------
POST /users                 Create a new account (get $1,000 starting balance)
POST /users/login           Sign in with username + password; returns user record
GET  /users/{id}            Get user profile + current balance
GET  /users/{id}/portfolio  All open positions with live P&L
"""

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market.api.schemas import CreateUserRequest, LoginRequest, PortfolioResponse, PositionSummary, UserResponse
from market.core.lmsr import liquidation_value, price as lmsr_price
from market.db.models import Market, Position, User
from market.db.session import get_db


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split(":", 1)
    except ValueError:
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return secrets.compare_digest(h.hex(), expected)

router = APIRouter(prefix="/users", tags=["users"])


# ──────────────────────────────────────────────────────────
# POST /users  — create account
# ──────────────────────────────────────────────────────────

@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user.  Grants a starting balance of **$1,000** virtual credits.
    Returns the new user's ID — save it, you'll need it as `X-User-Id` on every
    protected endpoint.
    """
    # Enforce uniqueness on username and email
    existing = await db.execute(
        select(User).where(
            (User.username == body.username) | (User.email == body.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Username or email is already taken.",
        )

    user = User(username=body.username, email=body.email,
                password_hash=_hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse.model_validate(user)


# ──────────────────────────────────────────────────────────
# POST /users/login  — sign in
# ──────────────────────────────────────────────────────────

@router.post("/login", response_model=UserResponse)
async def login_user(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Sign in with username and password.
    Returns the user record (including the ID needed for subsequent requests).
    """
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return UserResponse.model_validate(user)


# ──────────────────────────────────────────────────────────
# GET /users/{id}  — profile
# ──────────────────────────────────────────────────────────

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch a user's public profile and current balance."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return UserResponse.model_validate(user)


# ──────────────────────────────────────────────────────────
# GET /users/{id}/portfolio  — all positions with live P&L
# ──────────────────────────────────────────────────────────

@router.get("/{user_id}/portfolio", response_model=PortfolioResponse)
async def get_portfolio(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    Return the user's full portfolio:
    - Cash balance
    - All open and resolved positions
    - Current market value and unrealised P&L for each position
    """
    # Load user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Load positions + the associated market in one query
    rows = (await db.execute(
        select(Position, Market)
        .join(Market, Position.market_id == Market.id)
        .where(Position.user_id == user_id)
        .order_by(Market.created_at.desc())
    )).all()

    positions: list[PositionSummary] = []
    unrealized_total = 0.0

    for pos, market in rows:
        p = lmsr_price(market.q_yes, market.q_no, market.b)

        if market.status == "resolved":
            # Payout has already been credited; show the settled value.
            if market.outcome == "admitted":
                current_value = pos.yes_shares
            elif market.outcome == "rejected":
                current_value = pos.no_shares
            else:
                current_value = 0.0
        else:
            # True LMSR liquidation: accounts for price impact of selling.
            current_value = liquidation_value(
                market.q_yes, market.q_no, market.b,
                pos.yes_shares, pos.no_shares,
            )
        unrealized_pnl = current_value - pos.cost_basis

        # Only count open markets in the unrealised total
        if market.status == "open":
            unrealized_total += unrealized_pnl

        positions.append(PositionSummary(
            market_id      = market.id,
            school         = market.school,
            round          = market.round,
            status         = market.status,
            current_price  = round(p, 4),
            yes_shares     = round(pos.yes_shares, 4),
            no_shares      = round(pos.no_shares,  4),
            cost_basis     = round(pos.cost_basis,  4),
            current_value  = round(current_value,   4),
            unrealized_pnl = round(unrealized_pnl,  4),
        ))

    return PortfolioResponse(
        user             = UserResponse.model_validate(user),
        balance          = round(user.balance, 2),
        positions        = positions,
        unrealized_value = round(unrealized_total, 2),
    )
