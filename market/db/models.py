"""
models.py — SQLAlchemy ORM table definitions.

Four tables:
  users      — participants, each with a virtual credit balance
  markets    — one LMSR binary market per (student × school) application
  trades     — immutable ledger; one row per transaction, never deleted
  positions  — running tally of each user's current holdings per market

Design notes:
  • All primary keys are UUIDs (string) so rows are safe to expose in URLs.
  • `markets.q_yes` and `markets.q_no` are the live LMSR state — they are
    updated on every trade inside a database transaction.
  • `trades` is append-only; positions are the denormalised aggregate view.
  • `markets.ml_prob` is the ML model's prediction at creation time and
    never changes — it acts as the permanent reference point.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Float, ForeignKey, Integer, String, Text,
    DateTime, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    __allow_unmapped__ = True


# ──────────────────────────────────────────────────────────
# Users
# ──────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id:         Mapped[str]      = mapped_column(String,       primary_key=True, default=_uuid)
    username:   Mapped[str]      = mapped_column(String(64),   unique=True, nullable=False)
    email:      Mapped[str]      = mapped_column(String(256),  unique=True, nullable=False)
    # Virtual currency — starts at $1,000; no real money involved
    balance:    Mapped[float]    = mapped_column(Float,        nullable=False, default=1000.0)
    is_admin:   Mapped[bool]     = mapped_column(Boolean,      nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships (back-populated for convenience)
    markets:   list["Market"]   = relationship("Market",   back_populates="creator",
                                                foreign_keys="Market.creator_id")
    trades:    list["Trade"]    = relationship("Trade",    back_populates="user")
    positions: list["Position"] = relationship("Position", back_populates="user")


# ──────────────────────────────────────────────────────────
# Markets
# ──────────────────────────────────────────────────────────

class Market(Base):
    __tablename__ = "markets"

    id:         Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    # ── Application context (student profile) ──────────────────────────────
    school:      Mapped[str]           = mapped_column(String(128), nullable=False)
    round:       Mapped[str]           = mapped_column(String(8),   nullable=False, default="RD")
    # EA / ED / REA / RD / Rolling / QB

    gpa_uw:      Mapped[float | None]  = mapped_column(Float,   nullable=True)
    gpa_w:       Mapped[float | None]  = mapped_column(Float,   nullable=True)
    sat:         Mapped[int   | None]  = mapped_column(Integer, nullable=True)
    act:         Mapped[int   | None]  = mapped_column(Integer, nullable=True)
    gender:      Mapped[str   | None]  = mapped_column(String(32),  nullable=True)
    race:        Mapped[str   | None]  = mapped_column(String(64),  nullable=True)
    income_ord:  Mapped[int   | None]  = mapped_column(Integer, nullable=True)
    # 0 (low income) → 5 (high income), matches model encoding
    flair_field: Mapped[str   | None]  = mapped_column(String(64),  nullable=True)
    # STEM / Art_Hum / SocSci / Bus_Fin

    # ── Qualitative profile ────────────────────────────────────────────────
    extracurriculars: Mapped[str | None]   = mapped_column(Text,        nullable=True)
    llm_score:        Mapped[float | None] = mapped_column(Float,       nullable=True)
    llm_summary:      Mapped[str | None]   = mapped_column(String(512), nullable=True)

    # ── LMSR state ─────────────────────────────────────────────────────────
    # These two floats ARE the market. Updated atomically inside a DB
    # transaction on every trade. q_yes and q_no start at the seeded values
    # derived from ml_prob (see lmsr.seed_state).
    b:     Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    # Liquidity parameter. Larger b → smaller price impact per trade,
    # larger max loss for the house (b * ln(2)).
    q_yes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    q_no:  Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── ML model snapshot ─────────────────────────────────────────────────
    ml_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    # P(admitted) from XGBoost + Bayesian model at market creation time.
    # Immutable after creation — it's the reference baseline.

    # ── Market lifecycle ──────────────────────────────────────────────────
    status:  Mapped[str]           = mapped_column(String(16), nullable=False, default="open")
    # "open"     → trading active
    # "closed"   → no new trades (grace period before resolution)
    # "resolved" → outcome known, payouts complete

    outcome: Mapped[str | None]    = mapped_column(String(16), nullable=True)
    # null until resolved; then "admitted" | "rejected"

    created_at:  Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_now)
    resolves_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional expected resolution date (for display only)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    creator:   "User"         = relationship("User",     back_populates="markets",
                                              foreign_keys=[creator_id])
    trades:    list["Trade"]    = relationship("Trade",    back_populates="market",
                                               order_by="Trade.created_at")
    positions: list["Position"] = relationship("Position", back_populates="market")


# ──────────────────────────────────────────────────────────
# Trades  (immutable ledger)
# ──────────────────────────────────────────────────────────

class Trade(Base):
    __tablename__ = "trades"

    id:        Mapped[str]      = mapped_column(String, primary_key=True, default=_uuid)
    market_id: Mapped[str]      = mapped_column(String, ForeignKey("markets.id"), nullable=False)
    user_id:   Mapped[str]      = mapped_column(String, ForeignKey("users.id"),   nullable=False)

    side:   Mapped[str] = mapped_column(String(4),  nullable=False)  # "yes" | "no"
    action: Mapped[str] = mapped_column(String(4),  nullable=False)  # "buy" | "sell"
    shares: Mapped[float] = mapped_column(Float, nullable=False)     # always positive

    # cost > 0 → trader paid (buy)
    # cost < 0 → trader received (sell)
    cost: Mapped[float] = mapped_column(Float, nullable=False)

    price_before: Mapped[float] = mapped_column(Float, nullable=False)
    price_after:  Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    market: "Market" = relationship("Market", back_populates="trades")
    user:   "User"   = relationship("User",   back_populates="trades")


# ──────────────────────────────────────────────────────────
# Positions  (live aggregate — updated after each trade)
# ──────────────────────────────────────────────────────────

class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("market_id", "user_id", name="uq_position_market_user"),
    )

    id:         Mapped[str]   = mapped_column(String, primary_key=True, default=_uuid)
    market_id:  Mapped[str]   = mapped_column(String, ForeignKey("markets.id"), nullable=False)
    user_id:    Mapped[str]   = mapped_column(String, ForeignKey("users.id"),   nullable=False)

    yes_shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    no_shares:  Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Net dollars spent (buys − sells).  Used to compute unrealised P&L:
    #   unrealised_pnl = current_value − cost_basis
    #   current_value  = yes_shares * price + no_shares * (1 − price)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    market: "Market" = relationship("Market", back_populates="positions")
    user:   "User"   = relationship("User",   back_populates="positions")
