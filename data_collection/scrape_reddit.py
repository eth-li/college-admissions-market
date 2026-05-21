"""
Scraper for r/collegeresults using two sources:

1. Reddit public JSON API — no auth required, covers ~1000 posts per listing
2. Arctic Shift archive API — public Reddit archive, covers full history

Both write to the same JSONL file and share the same checkpoint, so you can
run either or both without duplicating records.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

SUBREDDIT = "collegeresults"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT_FILE = RAW_DIR / "scraped_ids.txt"
OUTPUT_FILE = RAW_DIR / "posts.jsonl"

# Reddit blocks requests without a User-Agent
HEADERS = {"User-Agent": "college-admissions-research/1.0 (academic project)"}


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def load_seen_ids() -> set[str]:
    if not CHECKPOINT_FILE.exists():
        return set()
    return set(CHECKPOINT_FILE.read_text().splitlines())


def mark_seen(post_id: str, seen_ids: set[str]) -> None:
    seen_ids.add(post_id)
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(post_id + "\n")


# ---------------------------------------------------------------------------
# Shared record format
# ---------------------------------------------------------------------------

def make_record(post_id, title, selftext, score, created_utc, flair, url, source) -> dict:
    return {
        "id": post_id,
        "title": title,
        "selftext": selftext,
        "score": score,
        "created_utc": created_utc,
        "link_flair_text": flair,
        "url": url,
        "source": source,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def is_useful(selftext: str) -> bool:
    """Drop deleted/removed posts — nothing to parse."""
    return bool(selftext) and selftext not in ("[deleted]", "[removed]")


# ---------------------------------------------------------------------------
# Source 1: Reddit public JSON API
# Covers ~1000 posts per listing sort. No auth, just needs a User-Agent.
# Paginate using the `after` cursor (the fullname of the last post: t3_<id>).
# ---------------------------------------------------------------------------

def fetch_reddit_listing(sort: str, time_filter: str | None = None) -> list[dict]:
    """
    Fetch up to 1000 posts from a Reddit listing endpoint.
    sort: "new" | "top" | "hot"
    time_filter: "all" | "year" | "month" | "week" (only meaningful for sort=top)
    """
    base = f"https://www.reddit.com/r/{SUBREDDIT}/{sort}.json"
    params = {"limit": 100, "raw_json": 1}
    if time_filter:
        params["t"] = time_filter

    posts = []
    after = None

    for _ in range(10):  # 10 pages × 100 posts = 1000 max
        if after:
            params["after"] = after

        resp = requests.get(base, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 429:
            print("  Rate limited — waiting 60s")
            time.sleep(60)
            continue
        resp.raise_for_status()

        data = resp.json()["data"]
        children = data["children"]
        if not children:
            break

        for child in children:
            p = child["data"]
            posts.append(make_record(
                post_id=p["id"],
                title=p.get("title", ""),
                selftext=p.get("selftext", ""),
                score=p.get("score", 0),
                created_utc=p.get("created_utc"),
                flair=p.get("link_flair_text"),
                url=p.get("url", ""),
                source="reddit_json",
            ))

        after = data.get("after")
        if not after:
            break

        time.sleep(1)  # ~1 req/sec keeps us well under Reddit's rate limit

    return posts


def fetch_reddit_search(query: str) -> list[dict]:
    """Search within r/collegeresults. Same pagination as listings."""
    base = f"https://www.reddit.com/r/{SUBREDDIT}/search.json"
    params = {"q": query, "restrict_sr": 1, "sort": "new", "limit": 100, "raw_json": 1}

    posts = []
    after = None

    for _ in range(10):
        if after:
            params["after"] = after

        resp = requests.get(base, headers=HEADERS, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(60)
            continue
        resp.raise_for_status()

        data = resp.json()["data"]
        children = data["children"]
        if not children:
            break

        for child in children:
            p = child["data"]
            posts.append(make_record(
                post_id=p["id"],
                title=p.get("title", ""),
                selftext=p.get("selftext", ""),
                score=p.get("score", 0),
                created_utc=p.get("created_utc"),
                flair=p.get("link_flair_text"),
                url=p.get("url", ""),
                source="reddit_search",
            ))

        after = data.get("after")
        if not after:
            break

        time.sleep(1)

    return posts


# ---------------------------------------------------------------------------
# Source 2: Arctic Shift archive
# Public archive of historical Reddit data. Query by subreddit, paginate by
# timestamp. Covers years of history that Reddit's own API won't surface.
# Docs: https://arctic-shift.photon-reddit.com/api-docs
# ---------------------------------------------------------------------------

def fetch_arctic_shift(before_utc: int | None = None, after_utc: int | None = None) -> list[dict]:
    """
    Fetch a page of posts from Arctic Shift. Returns up to 100 posts.
    Use before_utc to paginate backwards through history.
    """
    base = "https://arctic-shift.photon-reddit.com/api/posts/search"
    params = {
        "subreddit": SUBREDDIT,
        "limit": 100,
        "sort": "desc",  # newest first within the window
    }
    if before_utc:
        params["before"] = before_utc
    if after_utc:
        params["after"] = after_utc

    resp = requests.get(base, headers=HEADERS, params=params, timeout=30)
    if resp.status_code == 429:
        print("  Arctic Shift rate limit — waiting 30s")
        time.sleep(30)
        return []
    resp.raise_for_status()

    items = resp.json().get("data", [])
    posts = []
    for p in items:
        posts.append(make_record(
            post_id=p["id"],
            title=p.get("title", ""),
            selftext=p.get("selftext", ""),
            score=p.get("score", 0),
            created_utc=p.get("created_utc"),
            flair=p.get("link_flair_text"),
            url=p.get("url", ""),
            source="arctic_shift",
        ))

    return posts


def scrape_arctic_shift_full() -> list[dict]:
    """
    Walk backwards through the subreddit's full history on Arctic Shift,
    100 posts at a time, until we get an empty page.
    """
    all_posts = []
    before = None

    with tqdm(desc="arctic_shift", unit="posts") as pbar:
        while True:
            batch = fetch_arctic_shift(before_utc=before)
            if not batch:
                break

            all_posts.extend(batch)
            pbar.update(len(batch))

            # Next page starts just before the oldest post in this batch
            oldest_ts = min(p["created_utc"] for p in batch if p["created_utc"])
            before = int(oldest_ts) - 1

            time.sleep(1)

    return all_posts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def save_new_posts(posts: list[dict], seen_ids: set[str], out_file) -> int:
    saved = 0
    for post in posts:
        if post["id"] in seen_ids:
            continue
        if not is_useful(post["selftext"]):
            mark_seen(post["id"], seen_ids)
            continue
        out_file.write(json.dumps(post) + "\n")
        mark_seen(post["id"], seen_ids)
        saved += 1
    return saved


def main():
    seen_ids = load_seen_ids()
    print(f"Already have {len(seen_ids)} post IDs on disk.")

    total = 0

    with open(OUTPUT_FILE, "a") as out_file:

        # --- Reddit public JSON (recent + popular posts) ---
        reddit_strategies = [
            ("top:all",   lambda: fetch_reddit_listing("top", "all")),
            ("top:year",  lambda: fetch_reddit_listing("top", "year")),
            ("top:month", lambda: fetch_reddit_listing("top", "month")),
            ("new",       lambda: fetch_reddit_listing("new")),
            ("search:results",   lambda: fetch_reddit_search("results")),
            ("search:decisions", lambda: fetch_reddit_search("decisions")),
            ("search:committed", lambda: fetch_reddit_search("committed")),
        ]

        for name, fetch in reddit_strategies:
            print(f"\nReddit JSON — {name}")
            posts = fetch()
            saved = save_new_posts(posts, seen_ids, out_file)
            print(f"  fetched {len(posts)}, saved {saved} new")
            time.sleep(2)

        # --- Arctic Shift (full historical archive) ---
        print("\nArctic Shift — full history")
        posts = scrape_arctic_shift_full()
        saved = save_new_posts(posts, seen_ids, out_file)
        print(f"  fetched {len(posts)}, saved {saved} new")
        total += saved

    print(f"\nDone. Total unique posts on disk: {len(seen_ids)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
