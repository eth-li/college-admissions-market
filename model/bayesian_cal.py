"""
bayesian_cal.py — Bayesian per-school logistic calibration.

Replaces Platt scaling with a principled model that anchors each school's
admission probability to the real IPEDS acceptance rate.

Model (per school s):
    P(admit | student) = σ(α_s + β · xgb_score)

    Prior:   α_s ~ N(logit(r_s), 1/λ)   — intercept anchored to IPEDS rate
             β   ~ N(0, σ_β²)             — global slope on XGBoost score

Fit via MAP estimation (scipy.optimize.minimize).  No MCMC needed.

Intuition:
  - Sparse schools (10–20 records): prior dominates → prediction close to IPEDS rate
  - Rich schools (100+ records): likelihood dominates → model trusts our data more
  - The slope β captures how much student quality moves the needle within a school
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

# How many "virtual observations" the IPEDS prior is worth.
# Higher → predictions stay closer to IPEDS rate.
# 30 ≈ "the prior is as strong as 30 training examples"
PRIOR_STRENGTH  = 30
BETA_PRIOR_STD  = 2.0   # prior std on the XGBoost slope

SCHOOL_STATS_FILE = Path(__file__).parent / "data" / "school_stats.json"

# Fallback accept rate for schools with no IPEDS data
FALLBACK_RATE = 0.40   # Reddit dataset mean; will be overridden for most schools


def _safe_logit(p: float, eps: float = 1e-6) -> float:
    return logit(np.clip(p, eps, 1 - eps))


def load_school_stats() -> dict[str, dict]:
    if not SCHOOL_STATS_FILE.exists():
        raise FileNotFoundError(
            f"Run `python3 model/fetch_school_stats.py` first to download IPEDS data."
        )
    with open(SCHOOL_STATS_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

def fit(
    xgb_scores:    np.ndarray,   # raw XGBoost P(admit) for each training record
    y:             np.ndarray,   # 0/1 labels
    school_labels: list[str],    # school name for each record
    school_stats:  dict,         # from load_school_stats()
    prior_strength: float = PRIOR_STRENGTH,
    beta_prior_std: float = BETA_PRIOR_STD,
) -> dict:
    """
    Fit the Bayesian calibration model.

    Returns a dict with:
      alphas       — {school: intercept}
      beta         — slope on XGBoost score
      school_stats — reference to IPEDS data
      global_alpha — fallback intercept for unseen schools
    """
    schools     = sorted(set(school_labels))
    school_idx  = {s: i for i, s in enumerate(schools)}
    n_schools   = len(schools)
    s_idx       = np.array([school_idx[s] for s in school_labels])

    # IPEDS acceptance rates (logit-space) as prior means for each school
    ipeds_rates = np.array([
        _safe_logit(school_stats.get(s, {}).get("accept_rate") or FALLBACK_RATE)
        for s in schools
    ])

    # Initial params: [α_0 ... α_{n-1}, β]
    x0 = np.append(ipeds_rates, 1.0)

    lam    = prior_strength
    sig_b2 = beta_prior_std ** 2

    def neg_log_posterior(params: np.ndarray) -> float:
        alphas = params[:n_schools]
        beta   = params[-1]

        logits   = alphas[s_idx] + beta * xgb_scores
        log_lik  = np.sum(
            y * np.log(expit(logits) + 1e-10) +
            (1 - y) * np.log(1 - expit(logits) + 1e-10)
        )

        # Prior on intercepts
        log_prior_a = -(lam / 2.0) * np.sum((alphas - ipeds_rates) ** 2)
        # Prior on slope
        log_prior_b = -(beta ** 2) / (2.0 * sig_b2)

        return -(log_lik + log_prior_a + log_prior_b)

    result = minimize(neg_log_posterior, x0, method="L-BFGS-B",
                      options={"maxiter": 2000, "ftol": 1e-12})

    alphas_opt = result.x[:n_schools]
    beta_opt   = result.x[-1]

    alpha_dict = {s: float(alphas_opt[i]) for s, i in school_idx.items()}

    # Global fallback: use the IPEDS median logit as intercept
    global_alpha = float(np.median(ipeds_rates))

    return {
        "alphas":       alpha_dict,
        "beta":         float(beta_opt),
        "global_alpha": global_alpha,
        "school_stats": school_stats,
        "prior_strength": prior_strength,
    }


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------

def predict(
    xgb_scores:    np.ndarray,
    school_labels: list[str],
    cal_params:    dict,
) -> np.ndarray:
    """
    Apply Bayesian calibration to raw XGBoost probabilities.
    Returns calibrated P(admit) in [0, 1].
    """
    alphas       = cal_params["alphas"]
    beta         = cal_params["beta"]
    global_alpha = cal_params["global_alpha"]

    alpha_arr = np.array([alphas.get(s, global_alpha) for s in school_labels])
    logits    = alpha_arr + beta * xgb_scores
    return expit(logits)


def predict_one(
    xgb_score: float,
    school:    str,
    cal_params: dict,
) -> float:
    return float(predict(np.array([xgb_score]), [school], cal_params)[0])
