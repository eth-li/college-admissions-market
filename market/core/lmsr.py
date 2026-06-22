"""
lmsr.py — Logarithmic Market Scoring Rule (Hanson 2003).

Pure math — no I/O, no database, no side effects.

Binary market: YES shares pay $1 if the event occurs; NO shares pay $1 otherwise.
The market maker (house) always stands ready to buy or sell at the LMSR price.

────────────────────────────────────────────────────────────
Cost function:
    C(q_yes, q_no) = b · ln( e^(q_yes/b) + e^(q_no/b) )

Current YES price  (= current consensus probability):
    p = e^(q_yes/b) / ( e^(q_yes/b) + e^(q_no/b) )

Cost to buy Δ YES shares (money flows trader → house):
    cost = C(q_yes + Δ, q_no) − C(q_yes, q_no)

Maximum house loss per market:
    b · ln(2)  ≈ 0.693 · b

Seeding from an ML prior p₀:
    Set  q_yes = b · logit(p₀),  q_no = 0
    →  price(q_yes, q_no, b) == p₀  ✓
────────────────────────────────────────────────────────────
"""

import math

_EPS = 1e-9  # numerical floor to avoid log(0)


# ──────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────

def _logsumexp(a: float, b_: float) -> float:
    """Numerically stable  ln( e^a + e^b )."""
    m = max(a, b_)
    return m + math.log(math.exp(a - m) + math.exp(b_ - m))


# ──────────────────────────────────────────────────────────
# Core LMSR functions
# ──────────────────────────────────────────────────────────

def cost(q_yes: float, q_no: float, b: float) -> float:
    """LMSR cost function  C(q_yes, q_no)."""
    return b * _logsumexp(q_yes / b, q_no / b)


def price(q_yes: float, q_no: float, b: float) -> float:
    """
    Current YES probability — the price of one YES share.
    Always in (0, 1).
    """
    a = q_yes / b
    c = q_no  / b
    m = max(a, c)
    exp_a = math.exp(a - m)
    exp_c = math.exp(c - m)
    return exp_a / (exp_a + exp_c)


def trade_cost(
    q_yes: float,
    q_no: float,
    b: float,
    shares: float,
    side: str,
) -> float:
    """
    Net dollar cost to buy `shares` on `side` ('yes' or 'no').

    Positive  → trader pays (buying).
    Negative  → trader receives (selling — pass negative shares).

    Examples
    --------
    Buying 10 YES:   trade_cost(q_y, q_n, b, +10, 'yes') > 0
    Selling 10 YES:  trade_cost(q_y, q_n, b, -10, 'yes') < 0  (you get money back)
    """
    if side == "yes":
        return cost(q_yes + shares, q_no, b) - cost(q_yes, q_no, b)
    else:
        return cost(q_yes, q_no + shares, b) - cost(q_yes, q_no, b)


def new_state(
    q_yes: float,
    q_no: float,
    shares: float,
    side: str,
) -> tuple[float, float]:
    """Return updated (q_yes, q_no) after a trade of `shares` on `side`."""
    if side == "yes":
        return q_yes + shares, q_no
    else:
        return q_yes, q_no + shares


def price_after_trade(
    q_yes: float,
    q_no: float,
    b: float,
    shares: float,
    side: str,
) -> float:
    """YES price after a trade of `shares` on `side`."""
    q_y2, q_n2 = new_state(q_yes, q_no, shares, side)
    return price(q_y2, q_n2, b)


# ──────────────────────────────────────────────────────────
# Market initialization
# ──────────────────────────────────────────────────────────

def seed_state(prob: float, b: float) -> tuple[float, float]:
    """
    Return (q_yes, q_no) such that  price(q_yes, q_no, b) == prob.

    Implementation: sets q_no = 0, q_yes = b · logit(prob).
    This is the unique solution up to an additive constant (which cancels
    out in all price and cost calculations).
    """
    prob  = max(_EPS, min(1.0 - _EPS, prob))
    q_yes = b * math.log(prob / (1.0 - prob))   # = b · logit(prob)
    return q_yes, 0.0


def max_loss(b: float) -> float:
    """Maximum possible subsidy loss for the market maker on one market."""
    return b * math.log(2.0)


def entropy_scaled_b(prob: float, b_max: float) -> float:
    """
    Choose b proportional to the binary entropy of the opening probability.

    H(p) = -p·ln(p) - (1-p)·ln(1-p)  ∈ [0, ln(2)]

    b = b_max · H(p) / ln(2)

    At p=0.5 (maximum uncertainty) → b = b_max.
    As p → 0 or 1 (near-certain)   → b → 0.

    This keeps max_loss = b · ln(2) = b_max · H(p), so the house spends its
    subsidy budget proportionally to how much price discovery each market can
    generate.
    """
    prob = max(_EPS, min(1.0 - _EPS, prob))
    h = -prob * math.log(prob) - (1.0 - prob) * math.log(1.0 - prob)
    return b_max * h / math.log(2.0)


# ──────────────────────────────────────────────────────────
# Budget ↔ shares conversion
# ──────────────────────────────────────────────────────────

def shares_for_budget(
    q_yes: float,
    q_no: float,
    b: float,
    budget: float,
    side: str,
) -> float:
    """
    Binary search: maximum shares purchasable for exactly `budget` dollars
    on `side`.

    Upper bound derivation:
        trade_cost(..., n, side) ≥ n · p_initial
        → n ≤ budget / p_initial
    where p_initial is the marginal price of the first share on `side`.
    """
    if budget <= _EPS:
        return 0.0

    p_now = price(q_yes, q_no, b)
    p_side = p_now if side == "yes" else (1.0 - p_now)
    hi = budget / max(p_side, _EPS) * 1.01   # valid upper bound with a tiny buffer
    lo = 0.0

    for _ in range(64):   # 64 bisection steps → precision < 1e-15
        mid = (lo + hi) / 2.0
        c   = trade_cost(q_yes, q_no, b, mid, side)
        if c <= budget:
            lo = mid
        else:
            hi = mid

    return lo
