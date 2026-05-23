"""
fetch_school_stats.py — Download IPEDS admissions data and match to our school list.

Downloads:
  ADM2023.zip  (admissions counts, SAT/ACT ranges)
  HD2023.zip   (institution names and states)

Outputs:
  model/data/school_stats.json   — {school_name: {accept_rate, sat25, sat75, ...}}

Run:
  python3 model/fetch_school_stats.py
"""

import csv
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from rapidfuzz import fuzz, process

ROOT     = Path(__file__).parent.parent
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

IPEDS_ADM_URL = "https://nces.ed.gov/ipeds/datacenter/data/ADM2023.zip"
IPEDS_HD_URL  = "https://nces.ed.gov/ipeds/datacenter/data/HD2023.zip"
ADM_ZIP       = DATA_DIR / "adm2023.zip"
HD_ZIP        = DATA_DIR / "hd2023.zip"
OUT_FILE      = DATA_DIR / "school_stats.json"
CLEANED_FILE  = ROOT / "data" / "processed" / "cleaned.jsonl"

# ---------------------------------------------------------------------------
# Curated IPEDS name overrides for schools that fuzzy-match ambiguously
# Maps our canonical name → exact IPEDS INSTNM
# ---------------------------------------------------------------------------
IPEDS_NAME_OVERRIDES = {
    "Harvard":                                  "Harvard University",
    "Yale":                                     "Yale University",
    "Princeton":                                "Princeton University",
    "Columbia":                                 "Columbia University in the City of New York",
    "Cornell":                                  "Cornell University",
    "Brown":                                    "Brown University",
    "Dartmouth":                                "Dartmouth College",
    "Massachusetts Institute of Technology":    "Massachusetts Institute of Technology",
    "Stanford University":                      "Stanford University",
    "University of Chicago":                    "University of Chicago",
    "Duke University":                          "Duke University",
    "Northwestern University":                  "Northwestern University",
    "Johns Hopkins University":                 "Johns Hopkins University",
    "Vanderbilt University":                    "Vanderbilt University",
    "Washington University in St. Louis":       "Washington University in St Louis",
    "Georgetown University":                    "Georgetown University",
    "University of Notre Dame":                 "University of Notre Dame",
    "Carnegie Mellon University":               "Carnegie Mellon University",
    "Emory University":                         "Emory University",
    "Georgia Institute of Technology":          "Georgia Institute of Technology-Main Campus",
    "University of Michigan":                   "University of Michigan-Ann Arbor",
    "University of Virginia":                   "University of Virginia-Main Campus",
    "University of California, Berkeley":       "University of California-Berkeley",
    "University of California, Los Angeles":    "University of California-Los Angeles",
    "University of California, San Diego":      "University of California-San Diego",
    "University of California, Santa Barbara":  "University of California-Santa Barbara",
    "University of California, Irvine":         "University of California-Irvine",
    "University of California, Davis":          "University of California-Davis",
    "University of California, Santa Cruz":     "University of California-Santa Cruz",
    "University of California, Riverside":      "University of California-Riverside",
    "University of North Carolina at Chapel Hill": "University of North Carolina at Chapel Hill",
    "University of Illinois Urbana-Champaign":  "University of Illinois Urbana-Champaign",
    "University of Wisconsin-Madison":          "University of Wisconsin-Madison",
    "Pennsylvania State University":            "Pennsylvania State University-Main Campus",
    "University of Maryland, College Park":     "University of Maryland-College Park",
    "University of Minnesota Twin Cities":      "University of Minnesota-Twin Cities",
    "Virginia Polytechnic Institute and State University": "Virginia Polytechnic Institute and State University",
    "Ohio State University":                    "Ohio State University-Main Campus",
    "Stony Brook University":                   "Stony Brook University",
    "Binghamton University":                    "Binghamton University",
    "University of Massachusetts Amherst":      "University of Massachusetts Amherst",
    "Indiana University Bloomington":           "Indiana University-Bloomington",
    "University of Pittsburgh":                 "University of Pittsburgh-Pittsburgh Campus",
    "Michigan State University":                "Michigan State University",
    "North Carolina State University":          "North Carolina State University at Raleigh",
    "University of South Carolina":             "University of South Carolina-Columbia",
    "Florida State University":                 "Florida State University",
    "Texas A&M University":                     "Texas A&M University-College Station",
    "University of Texas at Austin":            "The University of Texas at Austin",
    "University of Washington":                 "University of Washington-Seattle Campus",
    "Rutgers University":                       "Rutgers University-New Brunswick",
    "University of Colorado Boulder":           "University of Colorado Boulder",
    "University of Florida":                    "University of Florida",
    "College of William & Mary":                "William & Mary",
    "Washington State University":              "Washington State University",
}


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  {dest.name} already cached")
        return
    print(f"  Downloading {url} ...")
    subprocess.run(["curl", "-sL", url, "-o", str(dest)], check=True)
    print(f"  Saved → {dest}")


def _load_csv_from_zip(zip_path: Path, encoding: str = "latin-1") -> list[dict]:
    with open(zip_path, "rb") as f:
        zf = zipfile.ZipFile(f)
        fname = zf.namelist()[0]
        raw = zf.open(fname).read()

    # Strip UTF-8 BOM if present
    if raw[:3] == b"\xef\xbb\xbf":
        text = raw.decode("utf-8-sig")
    else:
        text = raw.decode(encoding)

    return list(csv.DictReader(io.StringIO(text)))


# ---------------------------------------------------------------------------
# Build IPEDS school lookup
# ---------------------------------------------------------------------------

def build_ipeds_lookup(adm_rows: list[dict], hd_rows: list[dict]) -> dict[str, dict]:
    """Return {instnm: {accept_rate, sat25, sat75, act25, act75, state}} for all institutions."""

    hd_by_id = {r["UNITID"]: r for r in hd_rows}

    def _int(v):
        try:
            return int(v) if v and v not in (".", "") else None
        except ValueError:
            return None

    lookup: dict[str, dict] = {}
    for adm in adm_rows:
        uid  = adm["UNITID"]
        hd   = hd_by_id.get(uid, {})
        name = hd.get("INSTNM", "")
        if not name:
            continue

        applied  = _int(adm.get("APPLCN"))
        admitted = _int(adm.get("ADMSSN"))
        rate     = admitted / applied if applied and admitted else None

        sat_r25 = _int(adm.get("SATVR25")); sat_r75 = _int(adm.get("SATVR75"))
        sat_m25 = _int(adm.get("SATMT25")); sat_m75 = _int(adm.get("SATMT75"))
        sat25   = ((sat_r25 or 0) + (sat_m25 or 0)) or None
        sat75   = ((sat_r75 or 0) + (sat_m75 or 0)) or None

        lookup[name] = {
            "accept_rate": rate,
            "sat25": sat25,
            "sat75": sat75,
            "act25": _int(adm.get("ACTCM25")),
            "act75": _int(adm.get("ACTCM75")),
            "state": hd.get("STABBR", ""),
        }
    return lookup


# ---------------------------------------------------------------------------
# Match our school names → IPEDS
# ---------------------------------------------------------------------------

def match_schools(
    our_schools: list[str],
    ipeds_lookup: dict[str, dict],
) -> dict[str, dict]:
    """Return {our_name: ipeds_stats} for every school we can match."""

    ipeds_names = list(ipeds_lookup.keys())
    results: dict[str, dict] = {}
    unmatched: list[str] = []

    for school in our_schools:
        # 1. Try curated override first
        override = IPEDS_NAME_OVERRIDES.get(school)
        if override and override in ipeds_lookup:
            results[school] = {**ipeds_lookup[override], "ipeds_name": override, "match": "override"}
            continue

        # 2. Fuzzy match
        best = process.extractOne(school, ipeds_names, scorer=fuzz.token_sort_ratio, score_cutoff=70)
        if best:
            ipeds_name, score, _ = best
            results[school] = {**ipeds_lookup[ipeds_name], "ipeds_name": ipeds_name, "match": f"fuzzy({score})"}
        else:
            unmatched.append(school)

    return results, unmatched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Fetching IPEDS school stats ===\n")

    # Download
    _download(IPEDS_ADM_URL, ADM_ZIP)
    _download(IPEDS_HD_URL,  HD_ZIP)

    # Parse
    print("\nParsing IPEDS data...")
    adm_rows = _load_csv_from_zip(ADM_ZIP, encoding="latin-1")
    hd_rows  = _load_csv_from_zip(HD_ZIP,  encoding="utf-8-sig")
    ipeds    = build_ipeds_lookup(adm_rows, hd_rows)
    print(f"  {len(ipeds):,} institutions with admissions data")

    # Get our school list from cleaned data
    our_schools: set[str] = set()
    with open(CLEANED_FILE) as f:
        for line in f:
            r = json.loads(line.strip())
            our_schools.add(r["school"])
    our_schools = sorted(our_schools)
    print(f"  {len(our_schools)} unique schools in cleaned dataset")

    # Match
    print("\nMatching our schools to IPEDS...")
    matched, unmatched = match_schools(our_schools, ipeds)
    print(f"  Matched:   {len(matched)}")
    print(f"  Unmatched: {len(unmatched)}")
    if unmatched:
        print(f"  → {unmatched[:10]}")

    # Validate — show key schools
    print("\nKey school stats:")
    checks = ["Harvard", "Yale", "Princeton", "Massachusetts Institute of Technology",
              "Stanford University", "Cornell", "University of Michigan",
              "Northeastern University", "Indiana University Bloomington",
              "Georgia Institute of Technology"]
    for school in checks:
        if school in matched:
            s = matched[school]
            rate = f"{s['accept_rate']*100:.1f}%" if s['accept_rate'] else "N/A"
            print(f"  {school:<50s} {rate:>6}  SAT={s['sat25']}-{s['sat75']}  ACT={s['act25']}-{s['act75']}")

    # Save
    with open(OUT_FILE, "w") as f:
        json.dump(matched, f, indent=2)
    print(f"\nSaved {len(matched)} schools → {OUT_FILE}")


if __name__ == "__main__":
    main()
