"""
Parser for raw r/collegeresults posts.

Three-pass extraction strategy per post:
  1. Section-based  — track "Accepted:" / "Rejected:" headers, collect school
                      names from the lines that follow
  2. Inline         — lines where school name and outcome appear on the same line
  3. Narrative      — sentences like "rejected from X, Y and Z"

Outputs one JSONL record per (post × school) application pair.
"""

import json
import re
from pathlib import Path
from typing import Optional

RAW_FILE = Path(__file__).parent.parent / "data" / "raw" / "posts.jsonl"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = PROCESSED_DIR / "applications.jsonl"
STATS_FILE  = PROCESSED_DIR / "parse_stats.json"


# ---------------------------------------------------------------------------
# Outcome vocabulary
# ---------------------------------------------------------------------------

def classify_outcome(text: str) -> Optional[str]:
    t = text.lower()
    if re.search(r'\b(accept(?:ed)?|admit(?:ted)?)\b', t):   return 'admitted'
    if re.search(r'\b(reject(?:ed)?|den(?:ied|y))\b', t):   return 'rejected'
    if re.search(r'\b(waitlist(?:ed)?|wait.?list(?:ed)?)\b', t): return 'waitlisted'
    if re.search(r'\b(defer(?:red)?)\b', t):                 return 'deferred'
    if re.search(r'\b(withdraw(?:n)?|withdrew)\b', t):       return 'withdrawn'
    # Emoji shortcuts
    if any(c in text for c in '✅✓🎉🟢'):  return 'admitted'
    if any(c in text for c in '❌✗🔴'):    return 'rejected'
    if any(c in text for c in '⏳🟡'):     return 'waitlisted'
    return None


# A line is an outcome-only section header if it contains ONLY an outcome word
# (plus optional markdown, punctuation). E.g. "**Acceptances:**", "Rejected:"
_HEADER_RE = re.compile(
    r'^\s*\**\s*'
    r'(?:accepted|acceptances?|admitted?'
    r'|rejected?|rejections?|denied?|denials?'
    r'|waitlisted?|waitlists?|wl'
    r'|deferred?|deferrals?'
    r'|withdrawn?|withdrawals?)'
    r'\s*\**\s*[s]?\s*[:.]?\s*$',
    re.I
)

def as_section_header(line: str) -> Optional[str]:
    """If line is purely an outcome header, return the outcome; else None."""
    if not _HEADER_RE.match(line):
        return None
    return classify_outcome(line)


# ---------------------------------------------------------------------------
# School name heuristics
# ---------------------------------------------------------------------------

# Tokens that are never school names on their own
_NOISE = {
    'results', 'decisions', 'schools', 'colleges', 'universities',
    'acceptances', 'rejections', 'waitlists', 'deferrals', 'committed',
    'summary', 'tldr', 'tl;dr', 'update', 'notes', 'note',
    'ea', 'ed', 'rd', 'rea', 'screa', 'qb', 'questbridge',
    'n/a', 'na', 'none', 'pending', 'still', 'waiting',
}

# Application-round suffixes to strip before validation
_ROUND_SUFFIX_RE = re.compile(
    r'\s*(EA\d?|ED\d?|REA|SCREA|SCEA|QuestBridge|QB|RD|Rolling|Regular)\s*$', re.I
)

# Round keyword anywhere in a string (for section headers and inline lines)
_ROUND_RE = re.compile(
    r'\b(EA\d?|ED\d?|REA|SCREA|SCEA|QuestBridge|QB|RD|Rolling|Regular|'
    r'Early\s+Action|Early\s+Decision|Regular\s+Decision)\b', re.I
)

# A line that is ONLY a round label, e.g. "EA:", "ED1:", "RD:"
_ROUND_ONLY_HEADER_RE = re.compile(
    r'^\s*\**\s*(EA\d?|ED\d?|REA|SCREA|SCEA|QuestBridge|QB|RD|Rolling|Regular|'
    r'Early\s+Action|Early\s+Decision|Regular\s+Decision)\s*\**\s*[:.]?\s*$', re.I
)

_ROUND_MAP = {
    'ea': 'EA', 'ea1': 'EA', 'ea2': 'EA', 'earlyaction': 'EA', 'early action': 'EA',
    'ed': 'ED', 'ed1': 'ED', 'ed2': 'ED', 'earlydecision': 'ED', 'early decision': 'ED',
    'rea': 'REA', 'screa': 'REA', 'scea': 'REA',
    'questbridge': 'QB', 'qb': 'QB',
    'rd': 'RD', 'rolling': 'Rolling',
    'regular': 'RD', 'regulardecision': 'RD', 'regular decision': 'RD',
}

def extract_round(text: str) -> Optional[str]:
    """Return EA/ED/REA/QB/RD/Rolling if a round keyword is found, else None."""
    m = _ROUND_RE.search(text)
    if not m:
        return None
    raw = m.group(1).lower().replace(' ', '')
    return _ROUND_MAP.get(raw, m.group(1).upper())


def clean_school_candidate(raw: str) -> str:
    s = raw.strip()
    # Remove markdown bullets and leading punctuation
    s = re.sub(r'^[\s\*\-\+•·►▶→⇒\\]+', '', s)
    # Remove leading numbered list prefixes like "1. " or "6) "
    s = re.sub(r'^\d+[\.\)]\s*', '', s)
    # Remove emoji
    s = re.sub(r'[\U0001F000-\U0001FFFF✅❌⏳🟢🔴🟡]+', '', s)
    # Remove bold/italic markers
    s = re.sub(r'\*+', '', s)
    # Remove application round suffix
    s = _ROUND_SUFFIX_RE.sub('', s)
    # Remove trailing unmatched closing paren
    if s.endswith(')') and '(' not in s:
        s = s[:-1]
    # Remove trailing punctuation
    s = s.strip().rstrip('.,;:')
    return s.strip()


def is_valid_school(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 80:
        return False
    if name.lower() in _NOISE:
        return False
    # Must have at least one letter
    if not re.search(r'[A-Za-z]', name):
        return False
    # Mostly digits → not a school
    if re.match(r'^[\d\s\./\+\-]+$', name):
        return False
    # Filter stat-like lines: "GPA: 4.0", "SAT: 1550"
    if re.match(r'^(gpa|sat|act|uw|weighted)\s*[:/]', name, re.I):
        return False
    return True


# ---------------------------------------------------------------------------
# Pass 1: section-based extraction
# ---------------------------------------------------------------------------

def extract_section_results(lines: list[str]) -> list[dict]:
    """
    Walk lines top-to-bottom. When we hit an outcome header, store it as
    `current_outcome`. Subsequent non-header, non-empty lines are treated as
    school names under that outcome — until we hit another header or a line
    that looks like a new section (e.g. "Extracurriculars").
    """
    results = []
    current_outcome = None
    current_round = None  # set by section headers like "EA Acceptances:" or "ED:"

    # Patterns that signal we've left the results section
    _SECTION_BREAK_RE = re.compile(
        r'^\s*\**\s*(extracurricular|activities|essays?|awards?|honors?|'
        r'demographics?|academics?|testing|standardized|reflections?|'
        r'thoughts?|stats?|gpa|sat|act|intended|major|hooks?)\b',
        re.I
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Round-only header: "EA:", "ED1:", "RD:" — updates current_round, no outcome change
        if _ROUND_ONLY_HEADER_RE.match(stripped):
            current_round = extract_round(stripped)
            continue

        header_outcome = as_section_header(stripped)
        if header_outcome:
            current_outcome = header_outcome
            # Header may also carry a round: "EA Acceptances:" → round=EA
            r = extract_round(stripped)
            if r:
                current_round = r
            continue

        if _SECTION_BREAK_RE.match(stripped):
            current_outcome = None
            current_round = None
            continue

        if current_outcome is None:
            continue

        # This line should be a school name.
        # Extract round from the line before clean_school_candidate strips it.
        # Line-specific round overrides section round (e.g. "Cornell ED" under "Accepted:")
        line_round = extract_round(stripped) or current_round
        school = clean_school_candidate(stripped)
        line_outcome = classify_outcome(stripped) or current_outcome

        if is_valid_school(school):
            results.append({'school_raw': school, 'outcome': line_outcome,
                            'round': line_round, 'pass': 1})

    return results


# ---------------------------------------------------------------------------
# Pass 2: inline extraction (school + outcome on the same line)
# ---------------------------------------------------------------------------

# Separators between school name and outcome
_SEP_RE = re.compile(r'[:\-–—→\(\)]')

def extract_inline_results(lines: list[str]) -> list[dict]:
    """
    For each line, check if it contains both a school-like token and an
    outcome keyword. Split on common separators; left side = school, right
    side = outcome.
    """
    results = []

    for line in lines:
        outcome = classify_outcome(line)
        if outcome is None:
            continue

        # Split on first separator
        parts = _SEP_RE.split(line, maxsplit=1)
        if len(parts) < 2:
            # No separator — outcome word may be embedded in the school name;
            # skip to avoid false positives
            continue

        school_portion = parts[0]
        right = parts[1] if len(parts) > 1 else ''

        # The outcome keyword should be on the RIGHT side of the separator
        if classify_outcome(right) is None and classify_outcome(school_portion) is not None:
            # Outcome is on the left — e.g. "Rejected: Harvard" — swap
            school_portion = right

        # Extract round from school portion BEFORE clean_school_candidate strips it
        round_val = extract_round(school_portion)
        school_raw = clean_school_candidate(school_portion)

        if is_valid_school(school_raw):
            results.append({'school_raw': school_raw, 'outcome': outcome,
                            'round': round_val, 'pass': 2})

    return results


# ---------------------------------------------------------------------------
# Pass 3: narrative extraction
# e.g. "Rejected by Harvard and MIT." / "Deferred from Stanford, Columbia"
# ---------------------------------------------------------------------------

_NARRATIVE_RE = re.compile(
    r'\b(accept(?:ed)?|admit(?:ted)?|reject(?:ed)?|den(?:ied)?|'
    r'waitlist(?:ed)?|defer(?:red)?|withdraw(?:n)?)\b'
    r'\s+(?:from|by|into|to|at)\s+'
    r'([A-Z][^.!?\n]+)',
    re.I
)

def extract_narrative_results(text: str) -> list[dict]:
    results = []
    for m in _NARRATIVE_RE.finditer(text):
        outcome = classify_outcome(m.group(1))
        school_blob = m.group(2)
        # Split comma/and-separated school lists
        schools = re.split(r'\s*(?:,|and)\s*', school_blob)
        for s in schools:
            school = clean_school_candidate(s)
            if is_valid_school(school):
                results.append({'school_raw': school, 'outcome': outcome,
                                'round': None, 'pass': 3})
    return results


# ---------------------------------------------------------------------------
# Stats extraction
# ---------------------------------------------------------------------------

def extract_gpa(text: str) -> tuple[Optional[float], Optional[float]]:
    # "UW/W: 3.9/4.5" or bare "3.9/4.5"
    m = re.search(r'\b(\d\.\d+)\s*/\s*(\d\.\d+)\b', text)
    if m:
        uw, w = float(m.group(1)), float(m.group(2))
        if 0 < uw <= w <= 5.5:
            return uw, w
    # "GPA: 3.9" or "UW: 3.9"
    m = re.search(r'\b(?:gpa|uw)\s*[:\-=]\s*(\d\.\d+)', text, re.I)
    if m:
        val = float(m.group(1))
        if 0 < val <= 5.5:
            return val, None
    return None, None


def extract_sat(text: str) -> Optional[int]:
    m = re.search(r'\bSAT\s*(?:I|1)?\s*[:\-=]?\s*(\d{3,4})\b', text, re.I)
    if m:
        val = int(m.group(1))
        if 400 <= val <= 1600:
            return val
    # Subscores: "700RW, 800M" → sum
    m = re.search(r'(\d{3})\s*(?:RW|EBRW)[,\s]+(\d{3})\s*M\b', text, re.I)
    if m:
        total = int(m.group(1)) + int(m.group(2))
        if 400 <= total <= 1600:
            return total
    return None


def extract_act(text: str) -> Optional[int]:
    m = re.search(r'\bACT\s*[:\-=]?\s*(\d{2})\b', text, re.I)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 36:
            return val
    return None


def extract_field(text: str, label: str) -> Optional[str]:
    """Extract a labelled field like 'Gender: Male' from the post body.
    label is a raw regex pattern (not escaped)."""
    m = re.search(rf'\*{{0,2}}\s*{label}\s*\*{{0,2}}\s*[:\-]\s*([^\n\*]+)', text, re.I)
    if m:
        return m.group(1).strip()
    return None


def parse_flair(flair: Optional[str]) -> dict:
    if not flair:
        return {}
    # "3.8+|1500+/34+|STEM"
    m = re.match(r'^([\d.+]+)\|([\d/+]+)\|(.+)$', flair.strip())
    if not m:
        return {}
    return {
        'flair_gpa':   m.group(1),
        'flair_score': m.group(2),
        'flair_field': m.group(3),
    }


# ---------------------------------------------------------------------------
# Combine passes and build output records
# ---------------------------------------------------------------------------

def extract_all_results(text: str) -> list[dict]:
    lines = text.splitlines()

    seen: dict[str, dict] = {}  # school_lower → result (last one wins for dupes)

    for r in (
        extract_section_results(lines)
        + extract_inline_results(lines)
        + extract_narrative_results(text)
    ):
        key = r['school_raw'].lower()
        # Later passes override earlier only if they found a different outcome
        # (handles "Deferred → Rejected" updates)
        seen[key] = r

    return list(seen.values())


def parse_post(post: dict) -> Optional[list[dict]]:
    text = post.get('selftext', '')
    results = extract_all_results(text)

    # Require at least 2 school outcomes to qualify as a results post
    if len(results) < 2:
        return None

    gpa_uw, gpa_w = extract_gpa(text)
    sat = extract_sat(text)
    act = extract_act(text)
    flair_data = parse_flair(post.get('link_flair_text'))

    # Demographics — present in structured posts, absent in narrative ones
    gender  = extract_field(text, 'Gender')
    race    = extract_field(text, 'Race(?:/Ethnicity)?')
    state   = extract_field(text, 'Residence')
    income  = extract_field(text, 'Income(?:\\s+Bracket)?')
    school_type = extract_field(text, 'Type of School')
    major   = extract_field(text, 'Intended Major(?:\\(s\\))?')

    records = []
    for r in results:
        records.append({
            'post_id':     post['id'],
            'school_raw':  r['school_raw'],
            'outcome':     r['outcome'],
            'round':       r.get('round'),   # EA/ED/REA/QB/RD/Rolling or None
            'extract_pass': r['pass'],
            'gpa_uw':      gpa_uw,
            'gpa_w':       gpa_w,
            'sat':         sat,
            'act':         act,
            'gender':      gender,
            'race':        race,
            'state':       state,
            'income':      income,
            'school_type': school_type,
            'major':       major,
            'created_utc': post.get('created_utc'),
            **flair_data,
        })
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    posts = []
    with open(RAW_FILE) as f:
        for line in f:
            posts.append(json.loads(line))

    print(f"Loaded {len(posts)} raw posts")

    total_records = 0
    results_posts = 0
    skipped = 0

    # Extraction quality counters
    has_gpa = has_sat = has_act = has_gender = has_major = 0
    outcome_counts: dict[str, int] = {}
    pass_counts: dict[int, int] = {1: 0, 2: 0, 3: 0}

    with open(OUTPUT_FILE, 'w') as out:
        for post in posts:
            records = parse_post(post)
            if records is None:
                skipped += 1
                continue

            results_posts += 1
            for rec in records:
                out.write(json.dumps(rec) + '\n')
                total_records += 1

                outcome_counts[rec['outcome']] = outcome_counts.get(rec['outcome'], 0) + 1
                pass_counts[rec['extract_pass']] = pass_counts.get(rec['extract_pass'], 0) + 1

            # Count quality on first record (post-level fields are the same)
            r0 = records[0]
            if r0['gpa_uw']:  has_gpa    += 1
            if r0['sat']:     has_sat    += 1
            if r0['act']:     has_act    += 1
            if r0['gender']:  has_gender += 1
            if r0['major']:   has_major  += 1

    stats = {
        'raw_posts':      len(posts),
        'results_posts':  results_posts,
        'skipped_posts':  skipped,
        'total_records':  total_records,
        'avg_schools_per_post': round(total_records / max(results_posts, 1), 1),
        'field_coverage': {
            'gpa':    f'{100*has_gpa/max(results_posts,1):.0f}%',
            'sat':    f'{100*has_sat/max(results_posts,1):.0f}%',
            'act':    f'{100*has_act/max(results_posts,1):.0f}%',
            'gender': f'{100*has_gender/max(results_posts,1):.0f}%',
            'major':  f'{100*has_major/max(results_posts,1):.0f}%',
        },
        'outcome_distribution': outcome_counts,
        'extract_pass_distribution': pass_counts,
    }

    with open(STATS_FILE, 'w') as f:
        json.dump(stats, f, indent=2)

    print(f"\nResults posts:  {results_posts} / {len(posts)}")
    print(f"Total records:  {total_records} ({stats['avg_schools_per_post']} schools/post)")
    print(f"\nField coverage:")
    for k, v in stats['field_coverage'].items():
        print(f"  {k:8s}: {v}")
    print(f"\nOutcome distribution: {outcome_counts}")
    print(f"Extract pass:  {pass_counts}")
    print(f"\nOutput: {OUTPUT_FILE}")
    print(f"Stats:  {STATS_FILE}")


if __name__ == '__main__':
    main()
