"""
train.py — XGBoost binary classifier for P(admitted | student features, school).

Pipeline:
  1. Load cleaned.jsonl, engineer features
  2. Chronological holdout: newest 20% of posts → final test set (never touched
     during training or tuning)
  3. 5-fold StratifiedGroupKFold on the training pool (grouped by post_id so
     all rows from one student stay together; school target encoding computed
     within each fold to avoid leakage)
  4. Train final XGBoost on full training pool; calibrate with isotonic
     regression on a held-out calibration split
  5. Evaluate on the chronological test set
  6. Save: model artifacts + feature metadata to model/artifacts/

Run:
  python3 model/train.py
"""

import json
import pickle
import sys
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    roc_auc_score,
    log_loss,
    brier_score_loss,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

warnings.filterwarnings("ignore", category=UserWarning)

DATA_FILE    = ROOT / "data" / "processed" / "cleaned.jsonl"
ARTIFACT_DIR = ROOT / "model" / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Hyperparameters
# ---------------------------------------------------------------------------

XGB_PARAMS = dict(
    n_estimators     = 600,
    learning_rate    = 0.05,
    max_depth        = 5,
    subsample        = 0.8,
    colsample_bytree = 0.8,
    min_child_weight = 5,
    reg_alpha        = 0.1,
    reg_lambda       = 1.0,
    tree_method      = "hist",
    enable_categorical = True,
    eval_metric      = "logloss",
    early_stopping_rounds = 40,
    random_state     = 42,
)

N_FOLDS      = 5
TEST_FRAC    = 0.20   # chronological holdout fraction
CAL_FRAC     = 0.15   # fraction of training pool held out for isotonic calibration


# ---------------------------------------------------------------------------
# Feature mappings
# ---------------------------------------------------------------------------

# flair_gpa → midpoint numeric estimate (bucket ceiling - 0.1)
FLAIR_GPA_MAP = {
    "3.8+": 3.90,
    "3.6+": 3.70,
    "3.4+": 3.50,
    "3.2+": 3.30,
    "3.0+": 3.10,
    "2.8+": 2.90,
}

# flair_score → SAT midpoint (SAT component only)
FLAIR_SCORE_MAP = {
    "1500+/34+": 1550,
    "1400+/31+": 1460,
    "1300+/28+": 1360,
    "1200+/25+": 1260,
    "1100+/22+": 1160,
}

# ACT → SAT concordance (College Board official table)
ACT_TO_SAT = {
    36: 1590, 35: 1540, 34: 1500, 33: 1460, 32: 1430, 31: 1400,
    30: 1370, 29: 1340, 28: 1310, 27: 1280, 26: 1240, 25: 1210,
    24: 1180, 23: 1140, 22: 1110, 21: 1080, 20: 1040, 19: 1010,
    18: 970,  17: 930,  16: 890,  15: 850,  14: 800,
}

# Round → ordinal selectivity bonus (higher = more likely to be admitted)
ROUND_ORDER = {"ED": 3, "REA": 2, "EA": 1, "RD": 0, "Rolling": 0, "QB": 0}

# Race normalization
def _norm_race(raw: str) -> str:
    if not raw:
        return "Unknown"
    r = raw.strip().lower()
    if any(x in r for x in ["east asian", "chinese", "japanese", "korean", "taiwanese", "viet"]):
        return "East_Asian"
    if any(x in r for x in ["south asian", "indian", "desi", "bengali", "pakistani", "sri"]):
        return "South_Asian"
    if r in ("asian", "asian american") or r.startswith("asian ("):
        # Disambiguate generic "Asian" → bucket together as broadly Asian
        return "Asian_Other"
    if any(x in r for x in ["white", "caucasian", "european"]):
        return "White"
    if any(x in r for x in ["black", "african"]):
        return "Black"
    if any(x in r for x in ["hispanic", "latino", "latina", "latinx", "mexican", "cuban"]):
        return "Hispanic"
    if any(x in r for x in ["native", "indigenous", "american indian"]):
        return "Native_American"
    if any(x in r for x in ["middle eastern", "arab"]):
        return "Middle_Eastern"
    if any(x in r for x in ["mixed", "multiracial", "biracial", "multi"]):
        return "Mixed"
    return "Other"

# Income normalization → ordinal 0-5
def _norm_income(raw) -> int | None:
    """Map messy income strings to an ordinal 0–5 bucket."""
    if not raw or not isinstance(raw, str):
        return None
    r = raw.strip().lower()
    # High income signals
    if any(x in r for x in ["400k", "300k", "200k", "full pay", "high", "wealthy", "very wealthy"]):
        return 5
    if any(x in r for x in ["150k", "170k", "180k", "190k"]):
        return 4
    if any(x in r for x in ["upper middle", "100k", "120k", "130k", "140k"]):
        return 3
    if any(x in r for x in ["middle class", "middle-class", "70k", "80k", "90k"]):
        return 2
    if any(x in r for x in ["lower middle", "working", "50k", "60k", "65k"]):
        return 1
    if any(x in r for x in ["<30", "low income", "poor", "poverty", "30k", "free lunch", "title i"]):
        return 0
    return None

# Major field normalization (from flair_field)
def _norm_field(raw: str) -> str:
    if not raw:
        return "Unknown"
    r = raw.lower()
    if "stem" in r:
        return "STEM"
    if any(x in r for x in ["art", "hum", "english", "music", "film"]):
        return "Art_Hum"
    if any(x in r for x in ["soc", "social", "psych", "poli"]):
        return "SocSci"
    if any(x in r for x in ["bus", "fin", "econ", "account"]):
        return "Bus_Fin"
    return "Other"


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

CATEGORICAL_COLS = ["school", "round_norm", "gender_norm", "race_norm", "field_norm", "school_type_norm"]
NUMERIC_COLS     = ["best_gpa", "gpa_w", "best_score", "act", "income_ord", "round_ord",
                    "school_admit_rate",   # in-dataset rate (target-encoded per fold)
                    "ipeds_rate",          # real IPEDS acceptance rate
                    "score_pctile"]        # student score vs school's admitted SAT range

def _to_float(series: pd.Series) -> pd.Series:
    """Coerce a Series to float64, turning non-numeric values into NaN."""
    return pd.to_numeric(series, errors="coerce").astype("float64")


def build_features(df: pd.DataFrame, school_stats: dict | None = None) -> pd.DataFrame:
    """Return a new DataFrame with engineered feature columns.

    All numeric columns are explicitly cast to float64 and all categorical
    columns to the 'category' dtype so the schema is stable for single-row
    inference as well as batch training.

    school_stats (optional): output of fetch_school_stats.load_school_stats().
        When provided, adds ipeds_rate and score_pctile features.
    """

    out = pd.DataFrame(index=df.index)

    # --- Numeric: GPA ------------------------------------------------
    # Prefer explicit gpa_uw; fall back to flair_gpa midpoint
    flair_gpa = df["flair_gpa"].map(FLAIR_GPA_MAP)
    out["best_gpa"] = _to_float(df["gpa_uw"].combine_first(flair_gpa))
    out["gpa_w"]    = _to_float(df["gpa_w"])

    # --- Numeric: Test score -----------------------------------------
    # Prefer SAT; convert ACT to SAT equiv; fall back to flair_score midpoint
    act_as_sat    = _to_float(df["act"]).map(ACT_TO_SAT)
    flair_score   = df["flair_score"].map(FLAIR_SCORE_MAP)
    out["best_score"] = _to_float(df["sat"].combine_first(act_as_sat).combine_first(flair_score))
    out["act"]        = _to_float(df["act"])

    # --- Numeric: Income ordinal ------------------------------------
    out["income_ord"] = df["income"].apply(_norm_income).astype("float64")

    # --- Numeric: Round ordinal -------------------------------------
    out["round_ord"] = df["round"].map(ROUND_ORDER).fillna(0).astype("float64")

    # --- Categorical: school ----------------------------------------
    out["school"] = df["school"].astype("category")

    # --- Categorical: round (normalized) ----------------------------
    round_norm = df["round"].copy().astype(str)
    round_norm[~round_norm.isin(["RD", "EA", "ED", "REA"])] = "Other"
    out["round_norm"] = round_norm.astype("category")

    # --- Categorical: gender ----------------------------------------
    gender = df["gender"].fillna("Unknown").astype(str).str.strip().str.title()
    gender[~gender.isin(["Male", "Female"])] = "Other"
    out["gender_norm"] = gender.astype("category")

    # --- Categorical: race ------------------------------------------
    out["race_norm"] = df["race"].fillna("").astype(str).apply(_norm_race).astype("category")

    # --- Categorical: major field (from flair) ----------------------
    out["field_norm"] = df["flair_field"].fillna("").apply(_norm_field).astype("category")

    # --- Categorical: school type -----------------------------------
    stype = df["school_type"].fillna("Unknown").str.strip().str.title()
    stype[~stype.isin(["Public", "Private"])] = "Unknown"
    out["school_type_norm"] = stype.astype("category")

    # --- Placeholder for school admit rate (filled later per fold) --
    out["school_admit_rate"] = np.nan

    # --- IPEDS features (Option A + B: real acceptance rate & score range) --
    if school_stats:
        # Real acceptance rate from IPEDS
        out["ipeds_rate"] = _to_float(
            df["school"].map(lambda s: school_stats.get(s, {}).get("accept_rate"))
        )
        # Where student's score falls within the school's admitted SAT range.
        # 0 = at 25th pctile, 1 = at 75th pctile, negative = below, >1 = above.
        # Clipped to [-2, 2] to prevent extreme values from dominating.
        sat25 = _to_float(df["school"].map(lambda s: school_stats.get(s, {}).get("sat25")))
        sat75 = _to_float(df["school"].map(lambda s: school_stats.get(s, {}).get("sat75")))
        score_range = (sat75 - sat25).replace(0, np.nan)
        pctile = (out["best_score"] - sat25) / score_range
        out["score_pctile"] = pctile.clip(-2.0, 2.0)
    else:
        out["ipeds_rate"]   = np.nan
        out["score_pctile"] = np.nan

    return out


# ---------------------------------------------------------------------------
# School target encoding (per-fold, avoids leakage)
# ---------------------------------------------------------------------------

def encode_school_admit_rate(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val:   pd.DataFrame,
    global_mean: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute per-school mean(admitted) on the training fold and map it
    to both train and val.  Unknown schools in val get the global mean.
    """
    school_rate = (
        pd.Series(y_train, index=X_train["school"].values)
        .groupby(level=0).mean()
        .to_dict()
    )
    X_train = X_train.copy()
    X_val   = X_val.copy()
    X_train["school_admit_rate"] = X_train["school"].map(school_rate).fillna(global_mean)
    X_val["school_admit_rate"]   = X_val["school"].map(school_rate).fillna(global_mean)
    return X_train, X_val


# ---------------------------------------------------------------------------
# Single XGBoost fit (used inside CV and for the final model)
# ---------------------------------------------------------------------------

def fit_xgb(
    X_tr: pd.DataFrame, y_tr: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(**XGB_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    return model


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

def metrics(y_true, y_prob) -> dict:
    return {
        "auc":    round(roc_auc_score(y_true, y_prob), 4),
        "logloss": round(log_loss(y_true, y_prob), 4),
        "brier":  round(brier_score_loss(y_true, y_prob), 4),
    }


# ---------------------------------------------------------------------------
# Calibration helper (module-level so it's picklable)
# ---------------------------------------------------------------------------

def platt_calibrate(platt_model, raw_probs: np.ndarray) -> np.ndarray:
    """Apply Platt (logistic) calibration to an array of raw probabilities."""
    lo = np.log(raw_probs / (1 - raw_probs + 1e-9) + 1e-9).reshape(-1, 1)
    return platt_model.predict_proba(lo)[:, 1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # ── Load data ───────────────────────────────────────────────────────────
    print(f"Loading {DATA_FILE}")
    rows = []
    with open(DATA_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    df = pd.DataFrame(rows)
    df["label"] = (df["outcome"] == "admitted").astype(int)

    # Sort by post creation time for chronological split
    df = df.sort_values("created_utc", ascending=True).reset_index(drop=True)

    n = len(df)
    print(f"  {n:,} records  |  {df['school'].nunique()} schools  |  {df['post_id'].nunique()} posts")
    print(f"  Admitted: {df['label'].mean()*100:.1f}%")

    # ── Chronological train/test split ──────────────────────────────────────
    # Split by unique post_id to avoid student leakage across splits
    post_times = df.groupby("post_id")["created_utc"].min().sort_values()
    all_posts  = post_times.index.tolist()
    n_test_posts = int(len(all_posts) * TEST_FRAC)
    test_posts   = set(all_posts[-n_test_posts:])
    train_posts  = set(all_posts[:-n_test_posts])

    df_train = df[df["post_id"].isin(train_posts)].copy()
    df_test  = df[df["post_id"].isin(test_posts)].copy()

    print(f"\nChronological split ({1-TEST_FRAC:.0%} train / {TEST_FRAC:.0%} test):")
    print(f"  Train: {len(df_train):,} records  ({df_train['post_id'].nunique()} posts)")
    print(f"  Test:  {len(df_test):,} records  ({df_test['post_id'].nunique()} posts)")

    # ── Load IPEDS school stats (Option A + B) ──────────────────────────────
    from model.bayesian_cal import load_school_stats, fit as bayes_fit, predict as bayes_predict
    try:
        school_stats = load_school_stats()
        print(f"\nLoaded IPEDS stats for {len(school_stats)} schools")
    except FileNotFoundError:
        print("\nWARNING: school_stats.json not found — run fetch_school_stats.py first")
        print("  Continuing without IPEDS features (predictions will be less calibrated)")
        school_stats = None

    # ── Feature engineering ─────────────────────────────────────────────────
    print("Engineering features...")
    X_all_train = build_features(df_train, school_stats)
    X_test      = build_features(df_test,  school_stats)
    y_train_all = df_train["label"].values
    y_test      = df_test["label"].values

    feature_cols = CATEGORICAL_COLS + NUMERIC_COLS
    global_mean  = float(y_train_all.mean())

    # ── 5-fold CV ────────────────────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print(f"5-fold StratifiedGroupKFold (grouped by post_id)")
    print(f"{'─'*55}")

    sgkf    = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=42)
    groups  = df_train["post_id"].values
    fold_metrics = []

    for fold, (tr_idx, val_idx) in enumerate(
        sgkf.split(X_all_train, y_train_all, groups=groups), start=1
    ):
        X_tr  = X_all_train.iloc[tr_idx][feature_cols].copy()
        X_val = X_all_train.iloc[val_idx][feature_cols].copy()
        y_tr  = y_train_all[tr_idx]
        y_val = y_train_all[val_idx]

        # Target-encode school within this fold (no leakage)
        X_tr, X_val = encode_school_admit_rate(X_tr, y_tr, X_val, global_mean)

        model    = fit_xgb(X_tr, y_tr, X_val, y_val)
        y_prob   = model.predict_proba(X_val)[:, 1]
        m        = metrics(y_val, y_prob)
        fold_metrics.append(m)
        print(f"  Fold {fold}: AUC={m['auc']:.4f}  LogLoss={m['logloss']:.4f}  Brier={m['brier']:.4f}")

    print(f"  {'─'*44}")
    mean_auc  = np.mean([m["auc"]    for m in fold_metrics])
    mean_ll   = np.mean([m["logloss"] for m in fold_metrics])
    mean_br   = np.mean([m["brier"]  for m in fold_metrics])
    std_auc   = np.std( [m["auc"]    for m in fold_metrics])
    print(f"  Mean:   AUC={mean_auc:.4f} ± {std_auc:.4f}  LogLoss={mean_ll:.4f}  Brier={mean_br:.4f}")

    # ── Final model (train on full training pool) ────────────────────────────
    print(f"\n{'─'*55}")
    print("Training final model on full training pool...")

    # Hold out a chronological calibration split
    sorted_train_posts = sorted(train_posts,
                                key=lambda p: post_times.get(p, 0))
    cal_posts = set(sorted_train_posts[-int(len(sorted_train_posts) * CAL_FRAC):])
    fit_posts = train_posts - cal_posts

    df_fit = df_train[df_train["post_id"].isin(fit_posts)]
    df_cal = df_train[df_train["post_id"].isin(cal_posts)]

    X_fit = build_features(df_fit, school_stats)[feature_cols].copy()
    X_cal = build_features(df_cal, school_stats)[feature_cols].copy()
    y_fit = df_fit["label"].values
    y_cal = df_cal["label"].values

    # Compute in-dataset school admit rates from fit portion
    school_rate_global = (
        pd.Series(y_fit, index=df_fit["school"].values)
        .groupby(level=0).mean()
        .to_dict()
    )
    def _apply_school_rate(X: pd.DataFrame) -> pd.DataFrame:
        X = X.copy()
        X["school_admit_rate"] = X["school"].map(school_rate_global).fillna(global_mean)
        return X

    X_fit        = _apply_school_rate(X_fit)
    X_cal        = _apply_school_rate(X_cal)
    X_test_final = _apply_school_rate(build_features(df_test, school_stats)[feature_cols].copy())

    base_model = fit_xgb(X_fit, y_fit, X_cal, y_cal)
    print(f"  Best iteration: {base_model.best_iteration}")

    # ── Bayesian per-school calibration (Option C) ───────────────────────────
    # Uses IPEDS real acceptance rates as priors.
    # Fits: P(admit | student) = σ(α_school + β · xgb_score)
    # where α_school is regularised toward logit(ipeds_rate).
    print("  Fitting Bayesian per-school calibration (IPEDS priors)...")

    raw_probs_cal  = base_model.predict_proba(X_cal)[:, 1]
    cal_school_labels = df_cal["school"].tolist()

    bayes_params = bayes_fit(
        xgb_scores    = raw_probs_cal,
        y             = y_cal,
        school_labels = cal_school_labels,
        school_stats  = school_stats or {},
    )
    print(f"  Slope β = {bayes_params['beta']:.3f}  "
          f"(how much XGBoost score moves the probability within each school)")

    # ── Evaluation on held-out test set ─────────────────────────────────────
    raw_probs_test = base_model.predict_proba(X_test_final)[:, 1]
    cal_probs_test = bayes_predict(raw_probs_test, df_test["school"].tolist(), bayes_params)

    m_raw = metrics(y_test, raw_probs_test)
    m_cal = metrics(y_test, cal_probs_test)

    print(f"\n{'═'*55}")
    print("Final test-set evaluation (chronological holdout)")
    print(f"{'─'*55}")
    print(f"  Raw (uncalibrated):  AUC={m_raw['auc']:.4f}  LogLoss={m_raw['logloss']:.4f}  Brier={m_raw['brier']:.4f}")
    print(f"  Bayesian calibrated: AUC={m_cal['auc']:.4f}  LogLoss={m_cal['logloss']:.4f}  Brier={m_cal['brier']:.4f}")
    print(f"{'═'*55}")

    # Sanity check: compare predicted vs IPEDS rates for key schools
    print("\nCalibration check — predicted median vs IPEDS real rate:")
    df_test_copy = df_test.copy()
    df_test_copy["prob_cal"] = cal_probs_test
    by_school = (
        df_test_copy.groupby("school")["prob_cal"]
        .agg(["median", "count"])
        .sort_values("median")
    )
    check_schools = ["Harvard", "Yale", "Massachusetts Institute of Technology",
                     "Stanford University", "Cornell", "University of Michigan",
                     "Northeastern University", "Indiana University Bloomington"]
    for school in check_schools:
        if school in by_school.index and by_school.loc[school, "count"] >= 3:
            pred   = by_school.loc[school, "median"]
            n      = int(by_school.loc[school, "count"])
            ipeds  = (school_stats or {}).get(school, {}).get("accept_rate")
            actual = df_test_copy[df_test_copy["school"] == school]["label"].mean()
            ipeds_str = f"{ipeds*100:.1f}%" if ipeds else "N/A"
            print(f"  {school:<45s}  pred={pred:.2%}  real={ipeds_str}  dataset={actual:.2%}  n={n}")

    # ── Feature importance ───────────────────────────────────────────────────
    print("\nTop feature importances (gain):")
    importance = base_model.get_booster().get_score(importance_type="gain")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1])[:14]:
        print(f"  {feat:<25s} {score:,.0f}")

    # ── Save artifacts ───────────────────────────────────────────────────────
    artifacts = {
        "model":            base_model,
        "bayes_params":     bayes_params,   # Bayesian calibration (replaces Platt)
        "school_stats":     school_stats,   # IPEDS data
        "school_rate":      school_rate_global,
        "global_mean":      global_mean,
        "feature_cols":     feature_cols,
        "cv_metrics":       fold_metrics,
        "test_metrics_raw": m_raw,
        "test_metrics_cal": m_cal,
    }
    out_path = ARTIFACT_DIR / "xgb_admission.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(artifacts, f)

    # Also save metadata as JSON for easy inspection
    meta = {
        "cv_mean_auc":  round(mean_auc, 4),
        "cv_std_auc":   round(std_auc, 4),
        "test_auc_cal": m_cal["auc"],
        "test_logloss_cal": m_cal["logloss"],
        "test_brier_cal": m_cal["brier"],
        "n_train": len(df_train),
        "n_test":  len(df_test),
        "n_schools": int(df["school"].nunique()),
        "bayes_beta": bayes_params["beta"],
        "ipeds_schools_matched": len(school_stats) if school_stats else 0,
        "feature_cols": feature_cols,
        "xgb_params": {k: v for k, v in XGB_PARAMS.items() if k != "early_stopping_rounds"},
    }
    with open(ARTIFACT_DIR / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved model → {out_path}")
    print(f"Saved metadata → {ARTIFACT_DIR / 'metadata.json'}")


if __name__ == "__main__":
    main()
