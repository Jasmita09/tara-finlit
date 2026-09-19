"""
market_data.py
===============
Fetches 30 days of daily price/volume history for BTC, ETH, and SOL from
CoinGecko's free public API (no API key required) and saves it locally as
JSON -- the raw material for the knowledge base in knowledge_base.py.

Run this once before building the knowledge base, and re-run whenever you
want fresher data (once a day is plenty for a 30-day window):

    python market_data.py

Output: data/raw/BTC.json, data/raw/ETH.json, data/raw/SOL.json
Each file is a list of {"date": "YYYY-MM-DD", "price_usd": float, "volume_usd": float}.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.request import urlopen

# CoinGecko coin ids -> the symbol we use everywhere else in this project
COINS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
}

DAYS = 30
OUT_DIR = Path("data/raw")


def fetch_coin_history(coin_id: str, days: int = DAYS) -> dict:
    """Fetch `days` of price/volume history for one coin from CoinGecko.
    Returns the raw parsed JSON, shaped like:
    {"prices": [[timestamp_ms, price], ...], "total_volumes": [[timestamp_ms, volume], ...]}
    """
    url = (
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        f"?vs_currency=usd&days={days}&interval=daily"
    )
    with urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bucket_by_day(series: list[list[float]]) -> dict[str, float]:
    """CoinGecko can return more than one point per calendar day depending
    on the requested range. Keep the LAST value seen for each UTC date, so
    downstream code gets exactly one number per day."""
    by_day: dict[str, float] = {}
    for ts_ms, value in series:
        date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[date_str] = value
    return by_day


def fetch_all() -> dict[str, list[dict]]:
    """Fetch and save daily price/volume series for every tracked coin.
    Returns {symbol: [daily records]} for whatever succeeded."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict]] = {}

    for coin_id, symbol in COINS.items():
        print(f"Fetching {symbol} ({coin_id})...")
        try:
            raw = fetch_coin_history(coin_id)
        except (URLError, HTTPError) as exc:
            print(f"  FAILED to fetch {symbol}: {exc}")
            continue

        prices_by_day = bucket_by_day(raw.get("prices", []))
        volumes_by_day = bucket_by_day(raw.get("total_volumes", []))

        daily = [
            {
                "date": date,
                "price_usd": prices_by_day[date],
                "volume_usd": volumes_by_day.get(date),
            }
            for date in sorted(prices_by_day)
        ]

        out_path = OUT_DIR / f"{symbol}.json"
        out_path.write_text(json.dumps(daily, indent=2))
        print(f"  Saved {len(daily)} days -> {out_path}")
        results[symbol] = daily

        time.sleep(1.5)  # be polite to CoinGecko's free-tier rate limit

    return results


if __name__ == "__main__":
    fetched = fetch_all()
    if not fetched:
        print("\nNo data fetched -- check your network connection and try again.")
    else:
        print(f"\nDone. Fetched: {', '.join(fetched.keys())}")
        print("Next step: python knowledge_base.py")