"""
trades.py — Buy, sell, and browse trade history.

Routes
------
POST /markets/{id}/buy              Buy YES or NO shares (spend budget)
POST /markets/{id}/sell             Sell shares back to the house
GET  /markets/{id}/trades           Public trade feed for a market
GET  /markets/{id}/positions/{uid}  One user's current position + P&L
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from market.api.deps import get_current_user
from market.api.schemas import BuyRequest, SellRequest, TradeResponse
from market.core.lmsr import new_state, price, shares_for_budget, trade_cost
from market.db.models import Market, Position, Trade, User
from market.db.session import get_db

router = APIRouter(prefix="/markets", tags=["trades"])


# ──────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────

async def _get_or_create_position(
    db: AsyncSession, market_id: str, user_id: str
) -> Position:
    """
    Fetch the user's position in this market, or create a blank one if they
    don't have one yet.  Uses `flush()` so the new row gets a DB-assigned ID
    without committing the surrounding transaction.
    """
    result = await db.execute(
        select(Position).where(
            Position.market_id == market_id,
            Position.user_id   == user_id,
        )
    )
    pos = result.scalar_one_or_none()
    if not pos:
        pos = Position(market_id=market_id, user_id=user_id)
        db.add(pos)
        await db.flush()
    return pos


# ──────────────────────────────────────────────────────────
# POST /markets/{id}/buy
# ──────────────────────────────────────────────────────────

@router.post("/{market_id}/buy", response_model=TradeResponse, status_code=201)
async def buy(
    market_id:    str,
    body:         BuyRequest,
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Buy YES or NO shares up to `budget` dollars.

    **How the price is calculated:**
    The LMSR market maker always fills orders at the current market price.
    As you buy more shares on one side, `q_yes` (or `q_no`) increases,
    which raises (or lowers) the YES probability for the next buyer.

    You will never pay more than `budget`.  The actual cost may be slightly
    less due to rounding in the binary search.

    **Winning condition:**
    - YES shares pay $1.00 each if the student is admitted.
    - NO shares pay $1.00 each if the student is rejected.
    """
    # ── Load and lock the market ────────────────────────────────────────────
    # SQLite serialises writes at the DB level; Postgres would use FOR UPDATE.
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")
    if market.status != "open":
        raise HTTPException(status_code=400, detail=f"Market is {market.status}.")

    # ── LMSR: how many shares does budget buy? ──────────────────────────────
    shares = shares_for_budget(
        market.q_yes, market.q_no, market.b, body.budget, body.side
    )
    if shares < 1e-6:
        raise HTTPException(
            status_code=400,
            detail="Budget is too small to purchase any shares at the current price.",
        )

    cost = trade_cost(market.q_yes, market.q_no, market.b, shares, body.side)

    # ── Balance check ───────────────────────────────────────────────────────
    if cost > current_user.balance + 1e-6:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient balance: you have ${current_user.balance:.2f} "
                f"but this trade costs ${cost:.2f}."
            ),
        )

    # ── Execute ─────────────────────────────────────────────────────────────
    price_before = price(market.q_yes, market.q_no, market.b)

    # Update LMSR state
    market.q_yes, market.q_no = new_state(
        market.q_yes, market.q_no, shares, body.side
    )
    price_after = price(market.q_yes, market.q_no, market.b)

    # Deduct from user balance
    current_user.balance -= cost

    # Update (or create) the user's position in this market
    pos = await _get_or_create_position(db, market_id, current_user.id)
    if body.side == "yes":
        pos.yes_shares += shares
    else:
        pos.no_shares  += shares
    pos.cost_basis += cost

    # Append to the immutable trade ledger
    trade = Trade(
        market_id    = market_id,
        user_id      = current_user.id,
        side         = body.side,
        action       = "buy",
        shares       = shares,
        cost         = cost,
        price_before = price_before,
        price_after  = price_after,
    )
    db.add(trade)

    await db.commit()
    await db.refresh(trade)

    return TradeResponse.model_validate(trade)


# ──────────────────────────────────────────────────────────
# POST /markets/{id}/sell
# ──────────────────────────────────────────────────────────

@router.post("/{market_id}/sell", response_model=TradeResponse, status_code=201)
async def sell(
    market_id:    str,
    body:         SellRequest,
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Sell shares back to the LMSR market maker.

    **Revenue:**
    You receive:  `C(q_yes, q_no) − C(q_yes − shares, q_no)`
    (i.e., the decrease in the cost function, which is always positive
    when shares > 0 and your position is large enough).

    Selling before resolution locks in your current value.  You won't
    receive $1/share — you'll receive the current market value of those
    shares, which may be above or below what you paid.
    """
    # ── Load and lock the market ────────────────────────────────────────────
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")
    if market.status != "open":
        raise HTTPException(status_code=400, detail=f"Market is {market.status}.")

    # ── Load and verify position ────────────────────────────────────────────
    pos_result = await db.execute(
        select(Position).where(
            Position.market_id == market_id,
            Position.user_id   == current_user.id,
        )
    )
    pos = pos_result.scalar_one_or_none()
    if not pos:
        raise HTTPException(
            status_code=400, detail="You have no position in this market."
        )

    owned = pos.yes_shares if body.side == "yes" else pos.no_shares
    if body.shares > owned + 1e-6:
        raise HTTPException(
            status_code=400,
            detail=(
                f"You only own {owned:.4f} {body.side.upper()} shares "
                f"but tried to sell {body.shares:.4f}."
            ),
        )

    # ── Revenue: negative cost of "buying −shares" ─────────────────────────
    # trade_cost(..., −shares, side) is negative (you receive money)
    # So revenue = |trade_cost(q, q, b, -shares, side)|
    revenue = -trade_cost(market.q_yes, market.q_no, market.b, -body.shares, body.side)

    # ── Execute ─────────────────────────────────────────────────────────────
    price_before = price(market.q_yes, market.q_no, market.b)

    # Update LMSR state — selling reduces the outstanding share count
    market.q_yes, market.q_no = new_state(
        market.q_yes, market.q_no, -body.shares, body.side
    )
    price_after = price(market.q_yes, market.q_no, market.b)

    # Credit user balance
    current_user.balance += revenue

    # Reduce position
    if body.side == "yes":
        pos.yes_shares -= body.shares
    else:
        pos.no_shares  -= body.shares
    pos.cost_basis -= revenue  # reduce cost basis by what you received

    # Append to trade ledger
    # cost is stored as NEGATIVE here to indicate money received
    trade = Trade(
        market_id    = market_id,
        user_id      = current_user.id,
        side         = body.side,
        action       = "sell",
        shares       = body.shares,
        cost         = -revenue,      # negative = received, matches buy convention
        price_before = price_before,
        price_after  = price_after,
    )
    db.add(trade)

    await db.commit()
    await db.refresh(trade)

    return TradeResponse.model_validate(trade)


# ──────────────────────────────────────────────────────────
# GET /markets/{id}/trades  — public feed
# ──────────────────────────────────────────────────────────

@router.get("/{market_id}/trades", response_model=list[TradeResponse])
async def list_trades(
    market_id: str,
    skip:  int = Query(0,  ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Public trade feed for a market — newest first.
    Shows the price before and after each trade so you can see the
    market's price discovery over time.
    """
    exists = (await db.execute(
        select(Market.id).where(Market.id == market_id)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="Market not found.")

    trades = (await db.execute(
        select(Trade)
        .where(Trade.market_id == market_id)
        .order_by(Trade.created_at.desc())
        .offset(skip)
        .limit(limit)
    )).scalars().all()

    return [TradeResponse.model_validate(t) for t in trades]


# ──────────────────────────────────────────────────────────
# GET /markets/{id}/positions/{user_id}  — single position
# ──────────────────────────────────────────────────────────

@router.get("/{market_id}/positions/{user_id}")
async def get_position(
    market_id: str,
    user_id:   str,
    db:        AsyncSession = Depends(get_db),
):
    """
    Return a user's current position in a market, including:
    - How many YES and NO shares they hold
    - Their cost basis (net dollars spent)
    - The current market value of their position
    - Unrealised P&L (current value − cost basis)
    """
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")

    p = price(market.q_yes, market.q_no, market.b)

    pos_result = await db.execute(
        select(Position).where(
            Position.market_id == market_id,
            Position.user_id   == user_id,
        )
    )
    pos = pos_result.scalar_one_or_none()

    if not pos:
        # No position — return zeroes (not a 404; this is a valid empty state)
        return {
            "market_id":      market_id,
            "user_id":        user_id,
            "yes_shares":     0.0,
            "no_shares":      0.0,
            "cost_basis":     0.0,
            "current_price":  round(p, 4),
            "current_value":  0.0,
            "unrealized_pnl": 0.0,
        }

    current_value  = pos.yes_shares * p + pos.no_shares * (1.0 - p)
    unrealized_pnl = current_value - pos.cost_basis

    return {
        "market_id":      market_id,
        "user_id":        user_id,
        "yes_shares":     round(pos.yes_shares,    4),
        "no_shares":      round(pos.no_shares,     4),
        "cost_basis":     round(pos.cost_basis,    4),
        "current_price":  round(p,                 4),
        "current_value":  round(current_value,     4),
        "unrealized_pnl": round(unrealized_pnl,    4),
    }
