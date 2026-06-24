"""
markets.py — Market lifecycle endpoints.

Routes
------
GET  /markets                       List markets (filter by school / status)
GET  /markets/{id}                  Market detail + live price
GET  /markets/{id}/quote            Price quote preview (no DB write)
POST /markets/{id}/resolve          Resolve with actual outcome; pay winners (admin only)
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from market.api.deps import get_current_user
from market.api.schemas import (
    MarketResponse,
    PriceQuote,
    ResolveMarketRequest,
)
from market.core.lmsr import (
    max_loss,
    price,
    price_after_trade,
    shares_for_budget,
    trade_cost,
)
from market.db.models import Market, Position, Trade, User
from market.db.session import get_db

router = APIRouter(prefix="/markets", tags=["markets"])


# ──────────────────────────────────────────────────────────
# Response builder  (computes aggregate fields from DB)
# ──────────────────────────────────────────────────────────

async def _market_response(market: Market, db: AsyncSession) -> MarketResponse:
    """
    Build a MarketResponse, fetching trade count and total volume from the DB.
    Computed every time a market is returned — keeps the response always fresh.
    """
    # Single query: trade count + sum of |cost| for total volume
    row = (await db.execute(
        select(
            func.count(Trade.id),
            func.coalesce(func.sum(func.abs(Trade.cost)), 0.0),
        ).where(Trade.market_id == market.id)
    )).one()
    trade_count, total_volume = int(row[0]), float(row[1])

    current_price = price(market.q_yes, market.q_no, market.b)
    ml_p          = market.ml_prob
    price_change  = round(current_price - ml_p, 4) if ml_p is not None else None

    return MarketResponse(
        id               = market.id,
        creator_id       = market.creator_id,
        school           = market.school,
        round            = market.round,
        current_price    = round(current_price, 4),
        ml_prob          = round(ml_p, 4) if ml_p is not None else None,
        price_change     = price_change,
        b                = market.b,
        max_loss         = round(max_loss(market.b), 2),
        status           = market.status,
        outcome          = market.outcome,
        gpa_uw           = market.gpa_uw,
        gpa_w            = market.gpa_w,
        sat              = market.sat,
        act              = market.act,
        gender           = market.gender,
        race             = market.race,
        income_ord       = market.income_ord,
        flair_field      = market.flair_field,
        extracurriculars = market.extracurriculars,
        llm_score        = market.llm_score,
        llm_summary      = market.llm_summary,
        trade_count      = trade_count,
        total_volume     = round(total_volume, 2),
        created_at       = market.created_at,
        resolved_at      = market.resolved_at,
    )


# ──────────────────────────────────────────────────────────
# GET /markets  — list
# ──────────────────────────────────────────────────────────

@router.get("", response_model=list[MarketResponse])
async def list_markets(
    school: Optional[str] = Query(None, description="Partial school name filter"),
    status: Optional[str] = Query(None, pattern=r'^(open|closed|resolved)$'),
    skip:   int           = Query(0,  ge=0),
    limit:  int           = Query(20, ge=1, le=100),
    db:     AsyncSession  = Depends(get_db),
):
    """
    List markets, newest first.  Optionally filter by school name (partial
    match, case-insensitive) or lifecycle status.
    """
    q = (
        select(Market)
        .order_by(Market.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if school:
        q = q.where(Market.school.ilike(f"%{school}%"))
    if status:
        q = q.where(Market.status == status)

    markets = (await db.execute(q)).scalars().all()
    return [await _market_response(m, db) for m in markets]


# ──────────────────────────────────────────────────────────
# GET /markets/{id}  — single market
# ──────────────────────────────────────────────────────────

@router.get("/{market_id}", response_model=MarketResponse)
async def get_market(market_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch a single market by its ID."""
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")
    return await _market_response(market, db)


# ──────────────────────────────────────────────────────────
# GET /markets/{id}/quote  — trade preview (no DB write)
# ──────────────────────────────────────────────────────────

@router.get("/{market_id}/quote", response_model=PriceQuote)
async def get_quote(
    market_id: str,
    side:      str   = Query(..., pattern=r'^(yes|no)$'),
    budget:    float = Query(..., gt=0.0, le=10_000.0),
    db:        AsyncSession = Depends(get_db),
):
    """
    Preview a buy order: see how many shares you'd get, what they'd cost,
    and how much the price would move — without spending anything.

    Useful for the frontend to show "you'll get X shares at avg price Y"
    before the user clicks Confirm.
    """
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")
    if market.status != "open":
        raise HTTPException(status_code=400, detail=f"Market is {market.status}.")

    p_before = price(market.q_yes, market.q_no, market.b)
    shares   = shares_for_budget(market.q_yes, market.q_no, market.b, budget, side)
    cost     = trade_cost(market.q_yes, market.q_no, market.b, shares, side)
    p_after  = price_after_trade(market.q_yes, market.q_no, market.b, shares, side)

    return PriceQuote(
        side         = side,
        shares       = round(shares, 4),
        cost         = round(cost,   4),
        price_before = round(p_before, 4),
        price_after  = round(p_after,  4),
        avg_price    = round(cost / max(shares, 1e-9), 4),
    )


# ──────────────────────────────────────────────────────────
# POST /markets/{id}/resolve  — close market + pay winners
# ──────────────────────────────────────────────────────────

@router.post("/{market_id}/resolve", response_model=MarketResponse)
async def resolve_market(
    market_id:    str,
    body:         ResolveMarketRequest,
    current_user: User         = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
):
    """
    Resolve a market with the actual admissions outcome.

    **What happens:**
    - If `outcome = admitted`: every YES shareholder receives **$1.00 per share**.
    - If `outcome = rejected`: every NO shareholder receives **$1.00 per share**.
    - Losing shareholders receive $0.
    - Market status becomes `resolved`.

    Only the market's creator can resolve it (they're the one who knows
    the actual decision).

    The payout model: each share is worth $1 if it wins and $0 if it loses.
    The house subsidises the market by up to `b × ln(2)` dollars.
    """
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found.")
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only house admins can resolve markets.")
    if market.status != "open":
        raise HTTPException(status_code=409, detail=f"Market is already '{market.status}'.")

    # Load all positions that have shares on the winning side
    positions = (await db.execute(
        select(Position).where(Position.market_id == market_id)
    )).scalars().all()

    for pos in positions:
        winning_shares = (
            pos.yes_shares if body.outcome == "admitted" else pos.no_shares
        )
        if winning_shares > 1e-9:
            # Credit the winner's balance: 1 winning share = $1.00
            u_result = await db.execute(select(User).where(User.id == pos.user_id))
            winner   = u_result.scalar_one_or_none()
            if winner:
                winner.balance += winning_shares

    market.status      = "resolved"
    market.outcome     = body.outcome
    market.resolved_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(market)

    return await _market_response(market, db)
