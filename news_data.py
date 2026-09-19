"""
news_data.py
=============
Fetches roughly 30 days of crypto news headlines for BTC, ETH, and SOL from
public RSS feeds (CoinDesk, Cointelegraph, Decrypt) -- genuinely free, no
signup, no API key, and not subject to the pricing changes that hit
dedicated crypto-news APIs in 2026 (CryptoPanic's free developer plan and
CoinDesk Data/CryptoCompare's free news tier were both pulled back).

RSS feeds aren't pre-tagged by coin the way CryptoPanic's API was, so this
tags each article by keyword-matching its title/description (e.g.
"bitcoin"/"btc" -> BTC). An article that mentions more than one coin is
counted for each -- e.g. a "Bitcoin and Ethereum both rally" headline ends
up in both BTC.json and ETH.json.

IMPORTANT -- why you should run this more than once: a single RSS fetch
only ever sees a feed's current "most recent N" items (usually 25-40).
High-volume outlets publish so often that those 25-40 items might only
span a few days, not a full 30-day window. This script handles that by
ACCUMULATING: each run merges newly-seen headlines (deduped by URL) into
whatever was already saved, and only drops entries once they age past 30
days. Run it once a day (or a few times) over the course of the hackathon
and coverage fills in naturally, rather than being capped by whatever one
snapshot happened to catch.

Usage:
    python news_data.py

Output: data/news_raw/BTC.json, ETH.json, SOL.json
Each file is a list of {"date", "title", "url", "source"}.

News is OPTIONAL -- knowledge_base.py builds a working RAG store from price
data alone if this hasn't been run (see market_data.py).

Want a second source later? The GDELT Project (api.gdeltproject.org/api/v2/doc/doc)
is another free, keyless global news API worth adding if these feeds ever
don't cover something you need.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import urlopen, Request
import xml.etree.ElementTree as ET

DAYS = 30
OUT_DIR = Path("data/news_raw")

# Public RSS feeds -- no key, no signup. Add more sources here (e.g. The
# Block, Blockworks) if you want broader coverage; just point at their
# published RSS URL and everything downstream (parsing, tagging, filtering)
# works the same way.
FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "TheBlock": "https://www.theblock.co/rss.xml",
    "Blockworks": "https://blockworks.co/feed/",
    "Messari": "https://messari.io/rss",
    "CryptoBriefing": "https://cryptobriefing.com/feed/",
    # Solana's own subreddit -- a targeted fix for SOL specifically being
    # thinly covered by general crypto outlets next to BTC/ETH. "new" sort
    # keeps this to recent posts rather than all-time popular ones.
    "r/solana": "https://www.reddit.com/r/solana/new/.rss",
}

# Keyword matching per coin (word-boundary, case-insensitive). Bare "sol"
# would also match "solve"/"solar"/etc., so it requires "solana" or a
# standalone "SOL" token -- \b already prevents partial-word matches for
# both, this comment just flags it as the trickiest of the three.
COIN_PATTERNS = {
    "BTC": re.compile(r"\b(bitcoin|btc)\b", re.IGNORECASE),
    "ETH": re.compile(r"\b(ethereum|eth)\b", re.IGNORECASE),
    "SOL": re.compile(r"\b(solana|sol)\b", re.IGNORECASE),
}


def fetch_feed(url: str) -> str:
    """Most RSS servers reject requests with no User-Agent, so set one."""
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; TaraNewsBot/1.0)"})
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text: str) -> list[dict]:
    """Parse a standard RSS 2.0 feed into a list of
    {title, link, date (datetime), description}. Skips malformed feeds or
    items instead of raising, so one bad feed doesn't kill the whole run."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        description = (item.findtext("description") or "").strip()
        if not title or not pub_date_raw:
            continue
        try:
            pub_date = parsedate_to_datetime(pub_date_raw)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        items.append({"title": title, "link": link, "date": pub_date, "description": description})

    return items


def tag_coins(text: str) -> list[str]:
    """Return every coin symbol whose keyword pattern matches this text."""
    return [symbol for symbol, pattern in COIN_PATTERNS.items() if pattern.search(text)]


def load_existing(symbol: str) -> list[dict]:
    """Load whatever was saved from a previous run, so this run can add to
    it instead of starting over. Since a single RSS fetch only ever sees a
    feed's current "most recent N" items, running this script repeatedly
    over the course of the hackathon (once a day is plenty) is how you
    actually build up real 30-day coverage rather than whatever a single
    snapshot happened to catch."""
    path = OUT_DIR / f"{symbol}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def fetch_all(days: int = DAYS) -> dict[str, list[dict]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_coin: dict[str, list[dict]] = {
        symbol: load_existing(symbol) for symbol in ("BTC", "ETH", "SOL")
    }
    seen_urls: dict[str, set] = {
        symbol: {r["url"] for r in records} for symbol, records in by_coin.items()
    }

    for source_name, url in FEEDS.items():
        print(f"Fetching {source_name}...")
        try:
            xml_text = fetch_feed(url)
        except (URLError, HTTPError) as exc:
            print(f"  FAILED to fetch {source_name}: {exc}")
            continue

        entries = parse_rss(xml_text)
        kept = 0
        for entry in entries:
            if entry["date"] < cutoff:
                continue
            coins = tag_coins(entry["title"] + " " + entry["description"])
            if not coins:
                continue
            record = {
                "date": entry["date"].strftime("%Y-%m-%d"),
                "title": entry["title"],
                "url": entry["link"],
                "source": source_name,
            }
            for symbol in coins:
                if record["url"] in seen_urls[symbol]:
                    continue  # already have this one from a previous run
                by_coin[symbol].append(record)
                seen_urls[symbol].add(record["url"])
            kept += 1
        print(f"  {len(entries)} articles in feed, {kept} within {days} days and coin-tagged")
        time.sleep(1)  # be polite to each site's server

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for symbol, records in by_coin.items():
        # Drop anything that's aged out of the 30-day window since the last run
        records = [r for r in records if r["date"] >= cutoff.strftime("%Y-%m-%d")]
        records.sort(key=lambda r: r["date"])
        by_coin[symbol] = records
        out_path = OUT_DIR / f"{symbol}.json"
        out_path.write_text(json.dumps(records, indent=2))
        print(f"Saved {len(records)} {symbol} headlines -> {out_path}")

    return by_coin


if __name__ == "__main__":
    fetched = fetch_all()
    if not any(fetched.values()):
        print("\nNo news collected -- check your network connection and try again.")
    else:
        print("\nDone. Next step: python knowledge_base.py")
        print("Tip: re-run this script daily (or a few times over the hackathon) --")
        print("it accumulates new headlines instead of overwriting what it already has.")