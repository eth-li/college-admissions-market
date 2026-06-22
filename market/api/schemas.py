"""
schemas.py — Pydantic v2 request and response models.

Every HTTP endpoint has a matching Input (Request) and Output (Response) schema.
Pydantic validates incoming JSON automatically and serialises outgoing data.
If the wrong type is sent, FastAPI returns a 422 with a clear field-by-field error
message before your route function ever runs.

Naming convention:
  XxxRequest  — the JSON body the client sends IN
  XxxResponse — the JSON the server sends OUT
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64,
                          description="Unique display name")
    email:    str = Field(..., pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$',
                          description="Email address (must be unique)")
    password: str = Field(..., min_length=6, max_length=128,
                          description="Password (min 6 characters)")


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


class UserResponse(BaseModel):
    id:         str
    username:   str
    email:      str
    balance:    float   # current virtual credit balance in dollars
    created_at: datetime

    model_config = {"from_attributes": True}  # allows constructing from ORM objects


# ═══════════════════════════════════════════════════════════
# Markets
# ═══════════════════════════════════════════════════════════

class CreateMarketRequest(BaseModel):
    # Required: which school is this market about?
    school: str = Field(..., min_length=2, max_length=128,
                        description="Canonical school name, e.g. 'Harvard' or 'Stanford University'")

    # Application round — affects ML model prediction
    round: str = Field("RD", pattern=r'^(EA|ED|REA|RD|Rolling|QB)$',
                       description="Application round")

    # Student stats — all optional; more filled in = better ML prediction
    gpa_uw:      Optional[float] = Field(None, ge=0.0, le=4.0,   description="Unweighted GPA")
    gpa_w:       Optional[float] = Field(None, ge=0.0, le=5.5,   description="Weighted GPA")
    sat:         Optional[int]   = Field(None, ge=400, le=1600,   description="SAT total score")
    act:         Optional[int]   = Field(None, ge=1,   le=36,     description="ACT composite")
    gender:      Optional[str]   = Field(None, description="Gender (Male / Female / Other)")
    race:        Optional[str]   = Field(None, description="Race/ethnicity string")
    income_ord:  Optional[int]   = Field(None, ge=0,   le=5,
                                         description="Income bracket: 0=low … 5=high")
    flair_field: Optional[str]   = Field(None, description="Intended field: STEM / Art_Hum / SocSci / Bus_Fin")

    # Qualitative profile — fed to the LLM assessor for extracurricular rating
    extracurriculars: Optional[str] = Field(
        None,
        max_length=4000,
        description="Free-text description of extracurriculars, awards, and achievements",
    )


class MarketResponse(BaseModel):
    id:         str
    creator_id: str
    school:     str
    round:      str

    # Live price info
    current_price: float           # current YES probability after all trades
    ml_prob:       Optional[float] # ML model's opening prediction (never changes)
    price_change:  Optional[float] # current_price − ml_prob  (crowd vs model)

    # Market parameters
    b:        float
    max_loss: float   # b × ln(2) — worst-case house subsidy

    # Status
    status:  str             # "open" | "closed" | "resolved"
    outcome: Optional[str]  # null until resolved; "admitted" | "rejected"

    # Student profile snapshot
    gpa_uw: Optional[float]
    sat:    Optional[int]
    act:    Optional[int]

    # Qualitative profile
    extracurriculars: Optional[str]
    llm_score:        Optional[float]  # 1–10 scale from Claude assessment
    llm_summary:      Optional[str]    # one-sentence summary from Claude

    # Activity metrics
    trade_count:  int
    total_volume: float   # total dollars traded (buys + sells, absolute value)

    created_at:  datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ResolveMarketRequest(BaseModel):
    outcome: str = Field(..., pattern=r'^(admitted|rejected)$',
                         description="Actual admissions outcome")


# ═══════════════════════════════════════════════════════════
# Trades
# ═══════════════════════════════════════════════════════════

class BuyRequest(BaseModel):
    side:   str   = Field(..., pattern=r'^(yes|no)$',
                          description="'yes' = betting admitted, 'no' = betting rejected")
    budget: float = Field(..., gt=0.0, le=10_000.0,
                          description=(
                              "Maximum dollars to spend. "
                              "The LMSR market maker will give you as many shares as this buys "
                              "at the current price. You won't spend more than this amount."
                          ))


class SellRequest(BaseModel):
    side:   str   = Field(..., pattern=r'^(yes|no)$',
                          description="Which shares to sell back")
    shares: float = Field(..., gt=0.0,
                          description="Number of shares to sell. Must not exceed your current position.")


class TradeResponse(BaseModel):
    id:           str
    market_id:    str
    user_id:      str
    side:         str    # "yes" | "no"
    action:       str    # "buy" | "sell"
    shares:       float  # number of shares (always positive)
    cost:         float  # positive = you paid (buy); negative = you received (sell)
    price_before: float  # YES probability before this trade
    price_after:  float  # YES probability after this trade
    created_at:   datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════
# Price quote (trade preview — no DB write)
# ═══════════════════════════════════════════════════════════

class PriceQuote(BaseModel):
    """
    Preview of what a buy order would look like before committing.
    Returned by  GET /markets/{id}/quote?side=yes&budget=50
    """
    side:         str
    shares:       float  # shares you'd receive
    cost:         float  # dollars you'd pay (≤ budget)
    price_before: float  # YES probability now
    price_after:  float  # YES probability after the hypothetical trade
    avg_price:    float  # cost / shares — your average price per share


# ═══════════════════════════════════════════════════════════
# Portfolio (user-level aggregate view)
# ═══════════════════════════════════════════════════════════

class PositionSummary(BaseModel):
    """One row in a user's portfolio — their stake in a single market."""
    market_id:      str
    school:         str
    round:          str
    status:         str
    current_price:  float
    yes_shares:     float
    no_shares:      float
    cost_basis:     float   # net dollars spent
    current_value:  float   # yes_shares * price + no_shares * (1 - price)
    unrealized_pnl: float   # current_value − cost_basis


class PortfolioResponse(BaseModel):
    user:             UserResponse
    balance:          float           # cash on hand
    positions:        list[PositionSummary]
    unrealized_value: float           # sum of unrealized P&L across open markets
