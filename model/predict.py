"""
predict.py — Load trained model and return P(admitted) for a given applicant.

Usage (CLI):
  python3 model/predict.py \
      --school "Harvard" \
      --gpa 3.95 \
      --sat 1550 \
      --round ED \
      --race White \
      --gender Male \
      --income 4

Usage (Python):
  from model.predict import load_model, predict_admission
  artifacts = load_model()
  prob = predict_admission(artifacts, school="Harvard", gpa_uw=3.95, sat=1550)
  print(f"Admission probability: {prob:.1%}")
"""

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ARTIFACT_DIR = ROOT / "model" / "artifacts"
MODEL_PATH   = ARTIFACT_DIR / "xgb_admission.pkl"


def load_model() -> dict:
    """Load saved artifacts dict from disk."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found at {MODEL_PATH}. Run `python3 model/train.py` first."
        )
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


def predict_admission(
    artifacts: dict,
    school:      str,
    gpa_uw:      float | None = None,
    gpa_w:       float | None = None,
    sat:         int   | None = None,
    act:         int   | None = None,
    flair_gpa:   str   | None = None,
    flair_score: str   | None = None,
    round_:      str          = "RD",
    gender:      str   | None = None,
    race:        str   | None = None,
    income_ord:  int   | None = None,
    flair_field: str   | None = None,
    school_type: str   | None = None,
) -> float:
    """
    Return calibrated P(admitted) in [0, 1].

    Only `school` is required; all student-stat fields are optional.
    When no student-specific features are provided, returns the school's
    Bayesian baseline (≈ IPEDS acceptance rate).
    Missing values are handled natively by XGBoost (NaN → go-to default branch).
    """
    from scipy.special import expit

    model        = artifacts["model"]
    bayes_params = artifacts["bayes_params"]
    school_stats = artifacts.get("school_stats") or {}
    school_rate  = artifacts["school_rate"]
    global_mean  = artifacts["global_mean"]
    feature_cols = artifacts["feature_cols"]

    # If no student-specific features are given, return the school's Bayesian
    # baseline (expit(alpha_s)) which is anchored to the IPEDS accept rate.
    # Running XGBoost with all-NaN features produces an arbitrary score that
    # doesn't represent a "typical" student.
    student_features = [gpa_uw, gpa_w, sat, act, flair_gpa, flair_score,
                        gender, race, income_ord, flair_field]
    if all(v is None for v in student_features):
        alphas       = bayes_params["alphas"]
        global_alpha = bayes_params["global_alpha"]
        alpha_s = alphas.get(school, global_alpha)
        return float(np.clip(expit(alpha_s), 0.0, 1.0))

    # Build a one-row DataFrame matching the training schema
    row = {
        "school":      school,
        "round":       round_,
        "gpa_uw":      gpa_uw,
        "gpa_w":       gpa_w,
        "sat":         sat,
        "act":         act,
        "flair_gpa":   flair_gpa,
        "flair_score": flair_score,
        "gender":      gender,
        "race":        race,
        "income":      None,          # income_ord supplied directly below
        "flair_field": flair_field,
        "school_type": school_type,
    }
    df = pd.DataFrame([row])

    from model.train import build_features
    from model.bayesian_cal import predict_one as bayes_predict_one

    X = build_features(df, school_stats)[feature_cols].copy()

    # Override income_ord if provided directly (user supplied ordinal 0-5)
    if income_ord is not None:
        X["income_ord"] = float(income_ord)

    # School admit rate from training data
    X["school_admit_rate"] = school_rate.get(school, global_mean)

    raw_prob = model.predict_proba(X)[0, 1]
    cal_prob = float(np.clip(bayes_predict_one(raw_prob, school, bayes_params), 0.0, 1.0))
    return cal_prob


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Predict college admission probability.")
    parser.add_argument("--school",   required=True, help="Canonical school name")
    parser.add_argument("--gpa",      type=float,    help="Unweighted GPA (0–4.0)")
    parser.add_argument("--gpa-w",    type=float,    help="Weighted GPA")
    parser.add_argument("--sat",      type=int,      help="SAT total score (400–1600)")
    parser.add_argument("--act",      type=int,      help="ACT composite (1–36)")
    parser.add_argument("--round",    default="RD",  help="Application round: RD, EA, ED, REA")
    parser.add_argument("--gender",   default=None,  help="Male / Female / Other")
    parser.add_argument("--race",     default=None,  help="Race/ethnicity string")
    parser.add_argument("--income",   type=int,      help="Income ordinal 0 (low) – 5 (high)")
    parser.add_argument("--field",    default=None,  help="flair_field: STEM, Art/Hum, SocSci, Bus/Fin")
    args = parser.parse_args()

    artifacts = load_model()
    prob = predict_admission(
        artifacts,
        school     = args.school,
        gpa_uw     = args.gpa,
        gpa_w      = getattr(args, "gpa_w", None),
        sat        = args.sat,
        act        = args.act,
        round_     = args.round,
        gender     = args.gender,
        race       = args.race,
        income_ord = args.income,
        flair_field = args.field,
    )
    print(f"\n  School:  {args.school}")
    print(f"  Round:   {args.round}")
    print(f"  GPA:     {args.gpa or '—'}")
    print(f"  SAT:     {args.sat or '—'}   ACT: {args.act or '—'}")
    print(f"\n  ► Admission probability: {prob:.1%}\n")


if __name__ == "__main__":
    main()
