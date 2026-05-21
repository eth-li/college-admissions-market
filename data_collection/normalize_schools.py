"""
School name normalization — strict mode.

Pipeline per raw school name:
  1. Strip formatting artifacts (markdown, Reddit spoiler markup, emoji)
  2. Drop known false positives (outcome words, section headers, HTML)
  3. Alias lookup: maps abbreviations / variants → clean canonical name
     (canonical names are pre-validated — no reference check needed)
  4. Fuzzy match against the reference college list for everything else
     Uses partial_ratio so "Baylor" correctly matches "Baylor University".
     Threshold 82 — anything below is DISCARDED.

Records with no match are dropped rather than kept as-is, which is the
key change from the previous version.
"""

import json
import re
from pathlib import Path

from rapidfuzz import fuzz, process

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
REF_FILE      = Path(__file__).parent.parent / "data" / "reference" / "colleges.txt"
INPUT_FILE    = PROCESSED_DIR / "applications.jsonl"
OUTPUT_FILE   = PROCESSED_DIR / "normalized.jsonl"
UNMAPPED_FILE = PROCESSED_DIR / "unmapped_schools.json"

FUZZY_THRESHOLD = 82  # partial_ratio score (0-100) below which we discard


# ---------------------------------------------------------------------------
# Load reference college list
# ---------------------------------------------------------------------------

def load_reference() -> list[str]:
    if not REF_FILE.exists():
        raise FileNotFoundError(
            f"{REF_FILE} not found — run build_college_list.py first"
        )
    return [line.strip() for line in REF_FILE.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# False positives — drop immediately, before any matching
# ---------------------------------------------------------------------------

FALSE_POSITIVES = {
    "accept", "accepted", "acceptance", "acceptances",
    "reject", "rejected", "rejection", "rejections",
    "waitlist", "waitlisted", "waitlists",
    "defer", "deferred", "deferrals", "deferr",
    "denied", "denial", "deni", "admitt", "admitted",
    "withdrawn", "withdrew",
    "additional information", "edit", "essays", "notes", "tldr",
    "results", "decisions", "schools", "colleges", "update",
    "reflection", "reflections", "summary", "committed to",
    "honors college", "honors program",
    "major", "majors", "intended major",
    "extracurriculars", "activities", "awards", "honors",
    "demographics", "academics", "testing",
    "hooks", "type of school", "school type",
    "awaiting", "all", "other", "both", "all of them",
    "final thoughts", "overall", "thoughts",
    "&#x200b", "&amp", "x200b",
    "waiting on", "still waiting", "pending", "waiting",
    "none", "n/a", "na", "tbd",
}


# ---------------------------------------------------------------------------
# Alias dict — abbreviations / variants → canonical display name
# All keys are lowercase.
# ---------------------------------------------------------------------------

ALIASES: dict[str, str] = {}

def _add(canonical: str, *aliases: str) -> None:
    for a in aliases:
        ALIASES[a.lower()] = canonical

# Ivies
_add("Harvard",          "Harvard", "Harvard University", "Harvard College", "Harva", "harva")
_add("Yale",             "Yale", "Yale University", "Yale College", "yale")
_add("Princeton",        "Princeton", "Princeton University", "princeton")
_add("Columbia",         "Columbia", "Columbia University", "Columbia College", "columbia")
_add("Cornell",          "Cornell", "Cornell University", "cornell")
_add("University of Pennsylvania",
     "UPenn", "Upenn", "upenn", "Penn", "penn",
     "University of Pennsylvania", "u of penn")
_add("Brown",            "Brown", "Brown University", "brown")
_add("Dartmouth",        "Dartmouth", "Dartmouth College", "dartmouth")

# MIT / Caltech / Stanford
_add("Massachusetts Institute of Technology",
     "MIT", "mit", "Massachusetts Institute of Technology")
_add("California Institute of Technology",
     "Caltech", "caltech", "California Institute of Technology", "Cal Tech")
_add("Stanford University",
     "Stanford", "Stanford University", "Stanfo", "stanfo", "stanford")

# Top private universities
_add("University of Chicago",
     "UChicago", "Uchicago", "uchicago", "University of Chicago",
     "U of Chicago", "chicago")
_add("Johns Hopkins University",
     "Johns Hopkins", "JHU", "jhu", "Johns Hopkins University",
     "john hopkins", "johns hopkins")
_add("Northwestern University",
     "Northwestern", "Northwestern University", "northwestern", "NU")
_add("Duke University",
     "Duke", "Duke University", "duke")
_add("Vanderbilt University",
     "Vanderbilt", "Vanderbilt University", "vanderbilt", "Vandy", "vandy")
_add("Rice University",
     "Rice", "Rice University", "rice")
_add("Emory University",
     "Emory", "Emory University", "emory")
_add("Georgetown University",
     "Georgetown", "Georgetown University", "georgetown")
_add("University of Notre Dame",
     "Notre Dame", "University of Notre Dame", "notre dame", "UND")
_add("Carnegie Mellon University",
     "CMU", "cmu", "Carnegie Mellon", "Carnegie Mellon University",
     "carnegie mellon", "Carnegie-Mellon")
_add("Washington University in St. Louis",
     "WashU", "washu", "WUSTL", "wustl",
     "Washington University in St. Louis", "Washington University",
     "Wash U", "washington university in st. louis")
_add("Case Western Reserve University",
     "Case Western", "CWRU", "cwru",
     "Case Western Reserve University", "Case Western Reserve",
     "case western")
_add("Tufts University",
     "Tufts", "Tufts University", "tufts")
_add("Boston University",
     "Boston University", "BU", "bu", "boston university")
_add("Boston College",
     "Boston College", "BC", "boston college")
_add("Northeastern University",
     "Northeastern", "Northeastern University", "northeastern", "NEU")
_add("New York University",
     "NYU", "nyu", "New York University", "NYU Stern", "NYU Tisch",
     "nyu stern", "nyu tisch", "New York Univ")
_add("University of Southern California",
     "USC", "usc", "University of Southern California",
     "USC Viterbi", "usc viterbi", "USC Marshall")
_add("Fordham University",
     "Fordham", "Fordham University", "fordham")
_add("Tulane University",
     "Tulane", "Tulane University", "tulane")
_add("Wake Forest University",
     "Wake Forest", "Wake Forest University", "wake forest", "WFU")
_add("Villanova University",
     "Villanova", "Villanova University", "villanova")
_add("George Washington University",
     "GWU", "gwu", "George Washington University",
     "George Washington", "George Washington Univ")
_add("Syracuse University",
     "Syracuse", "Syracuse University", "syracuse")
_add("Lehigh University",
     "Lehigh", "Lehigh University", "lehigh")
_add("Rensselaer Polytechnic Institute",
     "RPI", "rpi", "Rensselaer Polytechnic Institute", "Rensselaer")
_add("Rochester Institute of Technology",
     "RIT", "rit", "Rochester Institute of Technology")
_add("Drexel University",
     "Drexel", "Drexel University", "drexel")
_add("Southern Methodist University",
     "SMU", "smu", "Southern Methodist University")
_add("Texas A&M University",
     "Texas A&M", "TAMU", "tamu", "Texas A&M University", "A&M")
_add("University of Texas at Dallas",
     "UT Dallas", "UTD", "utd", "University of Texas at Dallas")
_add("Babson College",
     "Babson", "Babson College", "babson")
_add("University of Miami",
     "University of Miami", "UMiami", "umiami", "U Miami")
_add("Brandeis University",
     "Brandeis", "Brandeis University", "brandeis")
_add("Worcester Polytechnic Institute",
     "WPI", "wpi", "Worcester Polytechnic Institute")

# UC System
_add("University of California, Berkeley",
     "UC Berkeley", "UCB", "ucb", "Berkeley",
     "University of California, Berkeley",
     "University of California Berkeley",
     "Cal", "cal", "uc berkeley")
_add("University of California, Los Angeles",
     "UCLA", "ucla",
     "University of California, Los Angeles",
     "University of California Los Angeles")
_add("University of California, San Diego",
     "UCSD", "ucsd", "UC San Diego",
     "University of California, San Diego",
     "University of California San Diego")
_add("University of California, Santa Barbara",
     "UCSB", "ucsb", "UC Santa Barbara",
     "University of California, Santa Barbara",
     "University of California Santa Barbara")
_add("University of California, Irvine",
     "UCI", "uci", "UC Irvine",
     "University of California, Irvine",
     "University of California Irvine")
_add("University of California, Davis",
     "UC Davis", "UCD", "ucd",
     "University of California, Davis",
     "University of California Davis")
_add("University of California, Santa Cruz",
     "UCSC", "ucsc", "UC Santa Cruz",
     "University of California, Santa Cruz",
     "University of California Santa Cruz")
_add("University of California, Riverside",
     "UCR", "ucr", "UC Riverside",
     "University of California, Riverside",
     "University of California Riverside")
_add("University of California, Merced",
     "UC Merced", "UCM", "ucm", "UC Merc", "uc merc",
     "University of California, Merced")

# Top public universities
_add("University of Michigan",
     "UMich", "Umich", "umich", "UMichigan", "Michigan",
     "University of Michigan", "U of Michigan",
     "University of Michigan-Ann Arbor",
     "UMich Ann Arbor", "UMich Ross", "umich ross",
     "Michigan Ross", "Ross School of Business")
_add("University of Virginia",
     "UVA", "uva", "University of Virginia",
     "U of Virginia")
_add("University of North Carolina at Chapel Hill",
     "UNC", "unc", "UNC Chapel Hill",
     "University of North Carolina",
     "University of North Carolina at Chapel Hill",
     "UNC-Chapel Hill")
_add("Georgia Institute of Technology",
     "Georgia Tech", "GT", "gt",
     "Georgia Institute of Technology",
     "GaTech", "gatech", "GA Tech", "gtech", "GTech")
_add("University of Illinois Urbana-Champaign",
     "UIUC", "uiuc",
     "University of Illinois Urbana-Champaign",
     "University of Illinois at Urbana-Champaign",
     "University of Illinois", "Illinois",
     "University of Illinois Urbana", "UIUC Grainger")
_add("University of Wisconsin-Madison",
     "UW Madison", "UWM",
     "University of Wisconsin-Madison",
     "University of Wisconsin Madison",
     "University of Wisconsin", "UW-Madison", "Wisconsin")
_add("University of Texas at Austin",
     "UT Austin", "ut austin",
     "University of Texas at Austin",
     "University of Texas", "UT", "Texas")
_add("Purdue University",
     "Purdue", "Purdue University", "purdue",
     "Purdue CS", "Purdue University West Lafayette")
_add("Pennsylvania State University",
     "Penn State", "PSU", "psu",
     "Pennsylvania State University",
     "Penn State University", "Penn State University Park")
_add("University of Maryland, College Park",
     "UMD", "umd", "University of Maryland",
     "University of Maryland College Park",
     "UMD College Park", "Maryland")
_add("University of Washington",
     "UW Seattle", "UW", "University of Washington",
     "University of Washington Seattle",
     "uw seattle", "UWashington")
_add("Virginia Polytechnic Institute and State University",
     "Virginia Tech", "VT", "vt",
     "Virginia Tech", "virginia tech",
     "Virginia Polytechnic Institute")
_add("Ohio State University",
     "Ohio State", "OSU", "osu",
     "Ohio State University", "The Ohio State University", "tOSU")
_add("Rutgers University",
     "Rutgers", "Rutgers University", "rutgers",
     "Rutgers New Brunswick")
_add("University of Florida",
     "UF", "uf", "University of Florida",
     "UFlorida", "uflorida", "UF Gainesville")
_add("University of Georgia",
     "UGA", "uga", "University of Georgia", "Georgia")
_add("North Carolina State University",
     "NC State", "NCSU", "ncsu",
     "North Carolina State University", "NC State University")
_add("Stony Brook University",
     "Stony Brook", "SBU", "sbu",
     "Stony Brook University", "SUNY Stony Brook")
_add("Binghamton University",
     "SUNY Binghamton", "Binghamton",
     "Binghamton University", "SUNY Bing")
_add("San Jose State University",
     "SJSU", "sjsu", "San Jose State University", "San Jose State")
_add("San Diego State University",
     "SDSU", "sdsu", "San Diego State University", "San Diego State")
_add("Arizona State University",
     "ASU", "asu", "Arizona State University", "Arizona State")
_add("University of Colorado Boulder",
     "CU Boulder", "CU",
     "University of Colorado Boulder",
     "University of Colorado", "Colorado Boulder")
_add("University of Rochester",
     "University of Rochester", "URochester", "Rochester",
     "U of Rochester")
_add("University of Pittsburgh",
     "Pitt", "pitt", "University of Pittsburgh",
     "UPitt", "upitt", "U Pittsburgh")
_add("University of Minnesota Twin Cities",
     "University of Minnesota", "UMN", "umn",
     "Minnesota", "U of Minnesota",
     "University of Minnesota Twin Cities")
_add("University of Toronto",
     "University of Toronto", "UofT", "U of Toronto", "UToronto")
_add("Indiana University Bloomington",
     "Indiana University", "IU", "iu",
     "IU Bloomington", "Indiana University Bloomington",
     "IU Kelley", "Indiana University")
_add("University of Massachusetts Amherst",
     "UMass Amherst", "UMass", "umass",
     "University of Massachusetts Amherst",
     "University of Massachusetts")
_add("University of Vermont",
     "UVM", "uvm", "University of Vermont", "Vermont")
_add("Clemson University",
     "Clemson", "Clemson University", "clemson")
_add("University of Connecticut",
     "UConn", "uconn", "University of Connecticut",
     "University of Connecticut Storrs")
_add("University of South Florida",
     "USF", "usf", "University of South Florida")
_add("University of Central Florida",
     "UCF", "ucf", "University of Central Florida")
_add("University of Alabama",
     "University of Alabama", "UA", "Alabama", "Bama")
_add("Florida State University",
     "Florida State", "FSU", "fsu",
     "Florida State University")
_add("College of William & Mary",
     "William & Mary", "William and Mary",
     "College of William and Mary",
     "College of William & Mary", "W&M")
_add("Michigan State University",
     "Michigan State", "MSU", "msu", "Michigan State University")
_add("Washington State University",
     "Washington State", "WSU", "wsu", "Washington State University")

# Liberal arts colleges
_add("Williams College",         "Williams", "Williams College", "williams")
_add("Amherst College",          "Amherst", "Amherst College", "amherst")
_add("Swarthmore College",       "Swarthmore", "Swarthmore College", "swarthmore")
_add("Pomona College",           "Pomona", "Pomona College", "pomona")
_add("Wellesley College",        "Wellesley", "Wellesley College", "wellesley")
_add("Bowdoin College",          "Bowdoin", "Bowdoin College", "bowdoin")
_add("Middlebury College",       "Middlebury", "Middlebury College", "middlebury")
_add("Colby College",            "Colby", "Colby College", "colby")
_add("Colgate University",       "Colgate", "Colgate University", "colgate")
_add("Barnard College",          "Barnard", "Barnard College", "barnard", "Barna", "barna")
_add("Wesleyan University",      "Wesleyan", "Wesleyan University", "wesleyan")
_add("Vassar College",           "Vassar", "Vassar College", "vassar")
_add("Smith College",            "Smith", "Smith College", "smith")
_add("Hamilton College",         "Hamilton", "Hamilton College", "hamilton")
_add("Harvey Mudd College",      "Harvey Mudd", "Harvey Mudd College", "harvey mudd", "HMC", "hmc")
_add("Claremont McKenna College","Claremont McKenna", "CMC", "cmc",
     "Claremont McKenna College", "claremont mckenna")
_add("Haverford College",        "Haverford", "Haverford College", "haverford", "Haverfo", "haverfo")
_add("Bryn Mawr College",        "Bryn Mawr", "Bryn Mawr College", "bryn mawr")
_add("Reed College",             "Reed", "Reed College", "reed")
_add("Oberlin College",          "Oberlin", "Oberlin College", "oberlin")
_add("Grinnell College",         "Grinnell", "Grinnell College", "grinnell")
_add("Macalester College",       "Macalester", "Macalester College", "macalester")
_add("Carleton College",         "Carleton", "Carleton College", "carleton")
_add("Davidson College",         "Davidson", "Davidson College", "davidson")
_add("College of the Holy Cross","Holy Cross", "College of the Holy Cross", "holy cross")
_add("Trinity College",          "Trinity", "Trinity College", "trinity college")
_add("Kenyon College",           "Kenyon", "Kenyon College", "kenyon")
_add("Bucknell University",      "Bucknell", "Bucknell University", "bucknell")
_add("Skidmore College",         "Skidmore", "Skidmore College", "skidmore")
_add("Bates College",            "Bates", "Bates College", "bates")
_add("Lafayette College",        "Lafayette", "Lafayette College", "lafayette")
_add("Denison University",       "Denison", "Denison University", "denison")
_add("Mount Holyoke College",    "Mount Holyoke", "Mount Holyoke College", "mount holyoke", "MHC")
_add("Scripps College",          "Scripps", "Scripps College", "scripps")
_add("Colorado College",         "Colorado College", "colorado college")
_add("Pitzer College",           "Pitzer", "Pitzer College", "pitzer")

# Washington & Lee
_add("Washington and Lee University",
     "Washington and Lee", "Washington & Lee", "W&L", "w&l",
     "Washington and Lee University")

# Oxford / Cambridge
_add("University of Oxford",      "Oxford", "University of Oxford", "oxford", "Oxfo", "oxfo")
_add("University of Cambridge",   "Cambridge", "University of Cambridge", "cambridge")

# UK / International
_add("University College London",
     "UCL", "ucl", "University College London", "university college london")
_add("Imperial College London",
     "Imperial College London", "Imperial", "imperial",
     "imperial college", "imperial college london")
_add("McGill University",          "McGill", "McGill University", "mcgill")
_add("University of Toronto",      "University of Toronto", "UofT", "uoft")

# Cal Poly
_add("California Polytechnic State University, San Luis Obispo",
     "Cal Poly SLO", "Cal Poly", "cal poly slo", "cal poly",
     "Cal Poly San Luis Obispo")
_add("California State Polytechnic University, Pomona",
     "Cal Poly Pomona", "cal poly pomona", "CPP")

# Sub-programs → parent institution
_add("University of Pennsylvania",  "UPenn Wharton", "Wharton", "wharton", "Penn Wharton")
_add("New York University",          "NYU Stern", "nyu stern", "NYU Tisch", "nyu tisch")
_add("University of Michigan",       "UMich Ross", "umich ross", "Michigan Ross")
_add("Indiana University Bloomington","IU Kelley", "iu kelley", "Kelley School of Business")
_add("Georgia Institute of Technology",
     "GaTech", "ga tech", "Georgia Tech CS", "georgia tech cs",
     "Georgia Tech OOS", "georgia tech oos")
_add("University of Illinois Urbana-Champaign",
     "UIUC CS", "uiuc cs", "UIUC Grainger", "uiuc grainger")
_add("Carnegie Mellon University",
     "CMU SCS", "cmu scs", "CMU CS", "cmu cs")

# More aliases for commonly dropped real schools
_add("Stony Brook University",       "Stonybrook", "stonybrook")
_add("Washington University in St. Louis",
     "WashU St. Louis", "washu st. louis", "Wash U St Louis")
_add("University of British Columbia",
     "UBC", "ubc", "University of British Columbia")
_add("University of Missouri",
     "Mizzou", "mizzou", "University of Missouri", "Mizzou Columbia")
_add("California State University, Long Beach",
     "CSULB", "csulb", "CSU Long Beach", "Cal State Long Beach",
     "Long Beach State")
_add("University of Maryland, Baltimore County",
     "UMBC", "umbc", "University of Maryland Baltimore County")
_add("University of Illinois at Chicago",
     "UIC", "uic", "University of Illinois Chicago",
     "University of Illinois at Chicago")
_add("SUNY Geneseo",
     "SUNY Geneseo", "Geneseo", "geneseo")
_add("Rhode Island School of Design",
     "RISD", "risd", "Rhode Island School of Design")
_add("Virginia Commonwealth University",
     "VCU", "vcu", "Virginia Commonwealth University")
_add("Louisiana State University",
     "LSU", "lsu", "Louisiana State University")
_add("New York Institute of Technology",
     "NYIT", "nyit", "New York Institute of Technology")
_add("University of Massachusetts Boston",
     "UMass Boston", "umass boston")
_add("University of Colorado Denver",
     "CU Denver", "cu denver", "University of Colorado Denver")
_add("University of Illinois Springfield",
     "UIS", "uis", "University of Illinois Springfield")

# Misc
_add("Baylor University",            "Baylor", "Baylor University", "baylor")
_add("Santa Clara University",       "Santa Clara", "Santa Clara University", "santa clara", "SCU")
_add("Providence College",           "Providence College", "Providence", "providence college")
_add("Colorado School of Mines",     "Colorado School of Mines", "Mines", "CSM", "mines")
_add("Hofstra University",           "Hofstra", "Hofstra University", "hofstra")
_add("University at Buffalo",        "SUNY Buffalo", "UB", "University at Buffalo", "SUNY at Buffalo")
_add("University of Richmond",       "University of Richmond", "Richmond", "UR")
_add("University of Delaware",       "University of Delaware", "Delaware", "UD", "ud")
_add("University of South Carolina", "University of South Carolina", "USC Columbia", "South Carolina")
_add("Florida International University", "FIU", "fiu", "Florida International University")
_add("University of Miami",          "UMiami", "University of Miami", "umiami", "U Miami")
_add("Pepperdine University",        "Pepperdine", "Pepperdine University", "pepperdine")
_add("Temple University",            "Temple", "Temple University", "temple")
_add("DePaul University",            "DePaul", "DePaul University", "depaul")
_add("Chapman University",           "Chapman", "Chapman University", "chapman")
_add("University of the Pacific",    "Pacific", "University of the Pacific")
_add("Loyola Marymount University",  "LMU", "lmu", "Loyola Marymount University", "Loyola Marymount")
_add("University of San Diego",      "USD", "usd", "University of San Diego")
_add("Stevens Institute of Technology",
     "Stevens Institute of Technology", "Stevens", "stevens")
_add("American University",          "American University", "AU", "american", "American")
_add("Juilliard School",             "Juilliard", "The Juilliard School", "juilliard", "Julliard")
_add("Savannah College of Art and Design",
     "SCAD", "scad", "Savannah College of Art and Design")


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

_ROUND_SUFFIX = re.compile(
    r'\s*(EA\d?|ED\d?|REA|SCREA|QuestBridge|QB|RD|Rolling|Regular)\s*$', re.I
)

def preprocess(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^>!|!<$', '', s).strip()           # Reddit spoiler markup
    s = re.sub(r'^[\s\*\-\+•·►▶→⇒\\]+', '', s)     # leading bullets/markdown
    s = re.sub(r'^\d+[\.\)]\s*', '', s)              # numbered list prefix
    s = re.sub(r'[\U0001F000-\U0001FFFF✅❌⏳🟢🔴🟡]+', '', s)  # emoji
    s = re.sub(r'\*+', '', s)                         # bold/italic markers
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s)           # trailing parens: "(REA)", "(RD)", "(EA)"
    s = _ROUND_SUFFIX.sub('', s)                      # bare EA/ED/RD suffix after parens removed
    if s.endswith(')') and '(' not in s:
        s = s[:-1]
    return s.strip().rstrip('.,;:').strip()


# ---------------------------------------------------------------------------
# Fuzzy validation against reference list
# ---------------------------------------------------------------------------

_REF: list[str] = []  # loaded in main()

def fuzzy_validate(name: str) -> str | None:
    """
    Returns the best matching college name from the reference list,
    or None if nothing scores >= FUZZY_THRESHOLD.
    partial_ratio is used so "Baylor" correctly matches "Baylor University".
    """
    if len(name) < 4:
        return None
    result = process.extractOne(
        name,
        _REF,
        scorer=fuzz.partial_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    return result[0] if result else None


# ---------------------------------------------------------------------------
# Normalize one raw school name
# ---------------------------------------------------------------------------

def normalize(school_raw: str) -> str | None:
    """
    Returns the canonical school name, or None to drop this record.
    """
    cleaned = preprocess(school_raw)
    lower = cleaned.lower()

    if not cleaned or len(cleaned) < 3:
        return None

    if lower in FALSE_POSITIVES:
        return None

    # Alias lookup — canonical names are hand-validated, no further check needed
    if lower in ALIASES:
        return ALIASES[lower]

    # Fuzzy match against the reference college list
    # We use the cleaned raw name (not a canonical) since it's not in the alias dict
    matched = fuzzy_validate(cleaned)
    return matched  # None means discard


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _REF
    _REF = load_reference()
    print(f"Reference list: {len(_REF)} colleges")

    records = []
    with open(INPUT_FILE) as f:
        for line in f:
            records.append(json.loads(line))
    print(f"Input: {len(records)} records")

    # Build a per-unique-name cache to avoid re-running fuzzy matching
    # on the same raw name thousands of times
    unique_raws = {r['school_raw'].strip() for r in records}
    print(f"Unique raw school names: {len(unique_raws)} — normalizing...")

    cache: dict[str, str | None] = {}
    for raw in unique_raws:
        cache[raw] = normalize(raw)

    kept = dropped = alias_hit = fuzzy_hit = 0
    unmapped: dict[str, int] = {}

    with open(OUTPUT_FILE, 'w') as out:
        for rec in records:
            raw = rec['school_raw'].strip()
            canonical = cache[raw]

            if canonical is None:
                dropped += 1
                unmapped[raw] = unmapped.get(raw, 0) + 1
                continue

            lower = preprocess(raw).lower()
            if lower in ALIASES:
                alias_hit += 1
            else:
                fuzzy_hit += 1

            round_val = rec.get('round') or 'RD'
            ordered = {'school': canonical, 'round': round_val}
            ordered.update({k: v for k, v in rec.items() if k != 'round'})
            out.write(json.dumps(ordered) + '\n')
            kept += 1

    # Save unmapped names appearing 3+ times for inspection
    frequent = {k: v for k, v in unmapped.items() if v >= 3}
    frequent_sorted = dict(sorted(frequent.items(), key=lambda x: -x[1]))
    with open(UNMAPPED_FILE, 'w') as f:
        json.dump(frequent_sorted, f, indent=2)

    print(f"\nKept:         {kept:,}  ({100*kept/len(records):.1f}%)")
    print(f"Dropped:      {dropped:,}  ({100*dropped/len(records):.1f}%)")
    print(f"  via alias:  {alias_hit:,}")
    print(f"  via fuzzy:  {fuzzy_hit:,}")
    print(f"\nFrequent unmapped (>=3): {len(frequent)} names")
    print("Top 20:")
    for name, count in list(frequent_sorted.items())[:20]:
        print(f"  {count:4d}  {repr(name)}")
    print(f"\nOutput:   {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
