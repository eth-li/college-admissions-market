"""
users.py — User account and portfolio endpoints.

Routes
------
POST /users                 Create a new account (get $1,000 starting balance)
GET  /users/{id}            Get user profile + current balance
GET  /users/{id}/portfolio  All open positions with live P&L
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market.api.schemas import CreateUserRequest, PortfolioResponse, PositionSummary, UserResponse
from market.core.lmsr import price as lmsr_price
from market.db.models import Market, Position, User
from market.db.session import get_db

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

    user = User(username=body.username, email=body.email)
    db.add(user)
    await db.commit()
    await db.refresh(user)

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

        # Current market value of this position
        current_value = pos.yes_shares * p + pos.no_shares * (1.0 - p)
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
