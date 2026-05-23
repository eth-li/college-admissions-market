"""
clean.py — Data cleaning step before model training.

Reads:  data/processed/normalized.jsonl
Writes: data/processed/cleaned.jsonl

Fixes applied:
  1. GPA_UW > 5.0  → cap at 4.0 (weighted GPA misreported as unweighted)
  2. Duplicate (post_id, school) rows → deduplicate, keep first occurrence
  3. Bad fuzzy matches → drop non-alias records where token_sort_ratio < 55
  4. Restrict to binary outcomes: admitted / rejected only
  5. Restrict to schools with >= MIN_RECORDS binary-outcome records

Run:
  python3 model/clean.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz

ROOT        = Path(__file__).parent.parent
INPUT_FILE  = ROOT / "data" / "processed" / "normalized.jsonl"
OUTPUT_FILE = ROOT / "data" / "processed" / "cleaned.jsonl"

MIN_RECORDS   = 10   # min binary-outcome records per school to be included
FUZZY_TSR_MIN = 55   # token_sort_ratio floor for fuzzy-matched (non-alias) records

# ---------------------------------------------------------------------------
# Import alias table from normalize_schools so we can tell alias vs fuzzy
# ---------------------------------------------------------------------------

sys.path.insert(0, str(ROOT / "data_collection"))
try:
    from normalize_schools import ALIASES, preprocess as _preprocess
    _HAS_ALIASES = True
except ImportError:
    _HAS_ALIASES = False
    ALIASES = {}
    _ROUND_SUFFIX = re.compile(
        r'\s*(EA\d?|ED\d?|REA|SCREA|QuestBridge|QB|RD|Rolling|Regular)\s*$', re.I
    )
    def _preprocess(raw: str) -> str:
        s = raw.strip()
        s = re.sub(r'^>!|!<$', '', s).strip()
        s = re.sub(r'^[\s\*\-\+•·►▶→⇒\\]+', '', s)
        s = re.sub(r'^\d+[\.\)]\s*', '', s)
        s = re.sub(r'[\U0001F000-\U0001FFFF✅❌⏳🟢🔴🟡]+', '', s)
        s = re.sub(r'\*+', '', s)
        s = re.sub(r'\s*\([^)]*\)\s*$', '', s)
        s = _ROUND_SUFFIX.sub('', s)
        if s.endswith(')') and '(' not in s:
            s = s[:-1]
        return s.strip().rstrip('.,;:').strip()


def _is_alias(school_raw: str) -> bool:
    return _HAS_ALIASES and _preprocess(school_raw).lower() in ALIASES


def _bad_fuzzy(school_raw: str, canonical: str) -> bool:
    """True if this fuzzy-matched record looks like a wrong mapping."""
    score = int(fuzz.token_sort_ratio(_preprocess(school_raw), canonical))
    return score < FUZZY_TSR_MIN


# ---------------------------------------------------------------------------
# GPA fix
# ---------------------------------------------------------------------------

def fix_gpa(r: dict) -> None:
    """Mutate record in place to fix implausible gpa_uw values."""
    gpa_uw = r.get("gpa_uw")
    if gpa_uw is None:
        return
    if gpa_uw > 5.0:
        # Almost certainly a weighted GPA.  Move to gpa_w if gpa_w is empty.
        if not r.get("gpa_w"):
            r["gpa_w"] = gpa_uw
        r["gpa_uw"] = None
    elif gpa_uw > 4.0:
        # Slightly over 4.0 on some scale — cap rather than null.
        r["gpa_uw"] = 4.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Reading {INPUT_FILE}")
    records: list[dict] = []
    with open(INPUT_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"  {len(records):,} records loaded\n")

    # 1. Fix GPA ----------------------------------------------------------
    gpa_nulled = gpa_capped = 0
    for r in records:
        before = r.get("gpa_uw")
        fix_gpa(r)
        after = r.get("gpa_uw")
        if before and before > 5.0:
            gpa_nulled += 1
        elif before and before != after:
            gpa_capped += 1
    print(f"Step 1 — GPA fix:")
    print(f"  gpa_uw > 5.0 moved to gpa_w (or nulled): {gpa_nulled}")
    print(f"  gpa_uw in (4.0, 5.0] capped to 4.0:      {gpa_capped}")

    # 2. Deduplicate (post_id, school) ------------------------------------
    seen: set[tuple] = set()
    deduped: list[dict] = []
    n_dups = 0
    for r in records:
        key = (r["post_id"], r["school"])
        if key in seen:
            n_dups += 1
        else:
            seen.add(key)
            deduped.append(r)
    records = deduped
    print(f"\nStep 2 — Deduplicate (post_id, school):")
    print(f"  Removed {n_dups:,} duplicate rows → {len(records):,} remaining")

    # 3. Bad fuzzy match filter -------------------------------------------
    clean: list[dict] = []
    n_bad = 0
    for r in records:
        raw = r.get("school_raw", "")
        if _is_alias(raw) or not _bad_fuzzy(raw, r["school"]):
            clean.append(r)
        else:
            n_bad += 1
    records = clean
    print(f"\nStep 3 — Bad fuzzy match filter (token_sort_ratio < {FUZZY_TSR_MIN}):")
    print(f"  Dropped {n_bad:,} records → {len(records):,} remaining")

    # 4. Binary outcomes only ---------------------------------------------
    binary = [r for r in records if r["outcome"] in ("admitted", "rejected")]
    print(f"\nStep 4 — Keep admitted / rejected only:")
    print(f"  Dropped {len(records) - len(binary):,} (waitlist/deferred/withdrawn) → {len(binary):,} remaining")
    records = binary

    # 5. School count filter ----------------------------------------------
    counts = Counter(r["school"] for r in records)
    valid  = {s for s, c in counts.items() if c >= MIN_RECORDS}
    filtered = [r for r in records if r["school"] in valid]
    print(f"\nStep 5 — School record count >= {MIN_RECORDS}:")
    print(f"  Kept {len(valid):,} schools, dropped {len(records) - len(filtered):,} records → {len(filtered):,} remaining")
    records = filtered

    # Summary -------------------------------------------------------------
    outcomes = Counter(r["outcome"] for r in records)
    n = len(records)
    print(f"\n{'─'*50}")
    print(f"Final cleaned dataset")
    print(f"{'─'*50}")
    print(f"  Records:        {n:,}")
    print(f"  Schools:        {len(valid):,}")
    print(f"  Unique posts:   {len({r['post_id'] for r in records}):,}")
    print(f"  Admitted:       {outcomes['admitted']:,}  ({100*outcomes['admitted']/n:.1f}%)")
    print(f"  Rejected:       {outcomes['rejected']:,}  ({100*outcomes['rejected']/n:.1f}%)")
    print()
    for field in ["gpa_uw", "gpa_w", "sat", "act", "gender", "race",
                  "income", "flair_gpa", "flair_score"]:
        filled = sum(1 for r in records if r.get(field) not in (None, ""))
        print(f"  {field:14s} coverage: {100*filled/n:4.1f}%")

    with open(OUTPUT_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
