"""
Download a reference list of real college names and save to data/reference/colleges.txt.

Source: Hipo university-domains-list (MIT licensed, ~9000 universities worldwide).
We keep US schools plus a curated set of commonly-mentioned international ones.

Run once; output is committed as reference data.
"""

import json
import requests
from pathlib import Path

REF_DIR = Path(__file__).parent.parent / "data" / "reference"
REF_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = REF_DIR / "colleges.txt"

URL = "https://raw.githubusercontent.com/Hipo/university-domains-list/master/world_universities_and_domains.json"

# Non-US countries whose universities appear frequently in r/collegeresults
INTERNATIONAL_COUNTRIES = {
    "United Kingdom", "Canada", "Australia", "Germany", "Netherlands",
    "Switzerland", "France", "Singapore", "Hong Kong", "Japan",
    "South Korea", "China", "India", "New Zealand", "Ireland",
    "Sweden", "Denmark", "Norway", "Finland", "Belgium", "Italy",
    "Spain", "Austria", "Israel",
}

# Canonical names from our alias dict that might not appear in the Hipo dataset
# (abbreviations like MIT expand to the full name that IS in the dataset;
#  short names like "Harvey Mudd" might not match perfectly — add them explicitly)
EXTRAS = [
    "MIT",
    "Harvey Mudd College",
    "United States Military Academy",
    "United States Naval Academy",
    "United States Air Force Academy",
    "United States Coast Guard Academy",
    "Olin College of Engineering",
    "Deep Springs College",
    "Minerva University",
    "The New School",
    "Pratt Institute",
    "Fashion Institute of Technology",
    "CUNY Baruch College",
    "CUNY Hunter College",
    "CUNY City College",
]


def main():
    print(f"Fetching {URL} ...")
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    universities = resp.json()
    print(f"Fetched {len(universities)} entries")

    names: set[str] = set()

    for u in universities:
        country = u.get("country", "")
        name = u.get("name", "").strip()
        if not name:
            continue
        if country == "United States" or country in INTERNATIONAL_COUNTRIES:
            names.add(name)

    # Add extras not well-covered by Hipo
    names.update(EXTRAS)

    sorted_names = sorted(names)
    OUTPUT.write_text("\n".join(sorted_names))

    print(f"Saved {len(sorted_names)} college names → {OUTPUT}")
    print(f"  US + international: {len(sorted_names) - len(EXTRAS)} from dataset")
    print(f"  Manual extras: {len(EXTRAS)}")


if __name__ == "__main__":
    main()
