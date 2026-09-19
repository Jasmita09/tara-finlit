"""
knowledge_base.py
===================
Turns raw daily price data (from market_data.py) AND raw news headlines
(from news_data.py) into a small, embedded knowledge base that grounds
Tara's answers in real, current BTC/ETH/SOL data instead of the model's own
(possibly stale) training knowledge.

Why text chunks instead of just handing the model a CSV of numbers?
---------------------------------------------------------------------
Embedding-based retrieval matches on MEANING. A chunk written as "BTC rose
4.2% this week, its best week of the month" retrieves correctly for a
question like "how has bitcoin been doing lately" -- a raw table of numbers
doesn't get matched the same way, and dumping the whole table into every
prompt wastes tokens. So the pipeline here is:

    raw daily prices + raw news headlines
    --> computed stats / weekly LLM summaries
    --> short text "facts"  -->  embedded  -->  stored
    --> retrieved by similarity at query time

Corpus size for 3 coins x 30 days is small (a few overview/correlation
chunks, ~12 weekly price chunks, plus news headline + weekly-digest chunks
-- typically well under 150 total), so this uses plain in-memory cosine
similarity instead of a vector database. There's nothing here that needs
one; a real vector DB would only add setup cost for no benefit at this scale.

Two different model providers are used here, deliberately:
  - EMBEDDING_MODEL (Gemini) does the embeddings. Embeddings aren't hit by
    the tight 20-requests/day cap Google put on free-tier text generation,
    so there's no reason to move this off Gemini -- and it's a genuine,
    substantial use of the Gemini API.
  - Weekly news-digest summarization (a text-generation task) uses the
    same DualProviderChat (Groq + Cerebras) as chat_engine.py, so it isn't
    competing with your interactive chat testing for the same scarce
    Gemini quota.

Usage:
    python market_data.py        # step 1a: fetch raw prices
    python news_data.py          # step 1b: fetch raw news (optional)
    python knowledge_base.py     # step 2: build chunks, embed, save to disk

Then chat_engine.py loads the saved store at runtime to ground answers.
News is optional: if data/news_raw/ is empty or missing, the price-only
knowledge base still builds fine.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from google import genai

from chat_providers import DualProviderChat

RAW_DIR = Path("data/raw")
NEWS_DIR = Path("data/news_raw")
STORE_PATH = Path("data/knowledge_store.json")
EMBEDDING_MODEL = "gemini-embedding-001"
SYMBOLS = ("BTC", "ETH", "SOL")


@dataclass
class Chunk:
    id: str
    text: str
    embedding: Optional[list[float]] = field(default=None)


def _embedding_vector(result) -> list[float]:
    """Pull the float vector out of an EmbedContentResponse."""
    embeddings = getattr(result, "embeddings", None)
    if embeddings:
        return list(embeddings[0].values)
    raise RuntimeError(f"Unexpected embed_content response shape: {result!r}")


# ------------------------------------------------------------------------ #
# Step 1: load raw data
# ------------------------------------------------------------------------ #

def load_daily(symbol: str) -> list[dict]:
    path = RAW_DIR / f"{symbol}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No raw data for {symbol} at {path}. Run `python market_data.py` first."
        )
    return json.loads(path.read_text())


def load_news(symbol: str) -> list[dict]:
    """News is optional -- return an empty list instead of raising if it
    hasn't been fetched, so the knowledge base still builds from price data
    alone."""
    path = NEWS_DIR / f"{symbol}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


# ------------------------------------------------------------------------ #
# Step 2: compute derived stats
# ------------------------------------------------------------------------ #

def daily_returns(daily: list[dict]) -> list[float]:
    """Day-over-day % change."""
    prices = [d["price_usd"] for d in daily]
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1] * 100
        for i in range(1, len(prices))
    ]


def pct_change(daily: list[dict]) -> float:
    """Overall % change from the first to the last day in the window."""
    return (daily[-1]["price_usd"] - daily[0]["price_usd"]) / daily[0]["price_usd"] * 100


def volatility(returns: list[float]) -> float:
    """Standard deviation of daily % returns -- a simple volatility proxy."""
    return statistics.pstdev(returns) if len(returns) > 1 else 0.0


def correlation(returns_a: list[float], returns_b: list[float]) -> float:
    """Pearson correlation between two daily-return series."""
    n = min(len(returns_a), len(returns_b))
    a, b = returns_a[-n:], returns_b[-n:]
    if n < 2:
        return 0.0
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b)) / n
    std_a, std_b = statistics.pstdev(a), statistics.pstdev(b)
    if std_a == 0 or std_b == 0:
        return 0.0
    return cov / (std_a * std_b)


# ------------------------------------------------------------------------ #
# Step 3: turn stats into short text "fact" chunks
# ------------------------------------------------------------------------ #

def build_overview_chunk(symbol: str, daily: list[dict], returns: list[float]) -> Chunk:
    start, end = daily[0], daily[-1]
    change = pct_change(daily)
    vol = volatility(returns)
    high = max(daily, key=lambda d: d["price_usd"])
    low = min(daily, key=lambda d: d["price_usd"])
    direction = "up" if change >= 0 else "down"
    vol_label = "high" if vol > 4 else "moderate" if vol > 2 else "low"

    text = (
        f"{symbol} 30-day overview ({start['date']} to {end['date']}): "
        f"price moved from ${start['price_usd']:,.2f} to ${end['price_usd']:,.2f}, "
        f"{direction} {abs(change):.1f}% overall. "
        f"30-day high was ${high['price_usd']:,.2f} on {high['date']}; "
        f"30-day low was ${low['price_usd']:,.2f} on {low['date']}. "
        f"Daily volatility (standard deviation of daily % returns) was "
        f"{vol:.2f}%, which is {vol_label} for a 30-day window."
    )
    return Chunk(id=f"{symbol}_overview", text=text)


def build_weekly_chunks(symbol: str, daily: list[dict]) -> list[Chunk]:
    chunks = []
    for week_num, i in enumerate(range(0, len(daily), 7), start=1):
        week = daily[i : i + 7]
        if len(week) < 2:
            continue
        change = (week[-1]["price_usd"] - week[0]["price_usd"]) / week[0]["price_usd"] * 100
        direction = "gained" if change >= 0 else "lost"
        text = (
            f"{symbol} week {week_num} of the last 30 days "
            f"({week[0]['date']} to {week[-1]['date']}): "
            f"{direction} {abs(change):.1f}%, moving from "
            f"${week[0]['price_usd']:,.2f} to ${week[-1]['price_usd']:,.2f}."
        )
        chunks.append(Chunk(id=f"{symbol}_week{week_num}", text=text))
    return chunks


def build_correlation_chunks(all_returns: dict[str, list[float]]) -> list[Chunk]:
    chunks = []
    symbols = list(all_returns.keys())
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            corr = correlation(all_returns[a], all_returns[b])
            strength = (
                "very strong" if abs(corr) > 0.8 else
                "strong" if abs(corr) > 0.6 else
                "moderate" if abs(corr) > 0.3 else
                "weak"
            )
            direction = "positive" if corr >= 0 else "negative"
            diversification_note = (
                "these two tend to move together, so holding both adds less "
                "risk diversification than it might appear to."
                if abs(corr) > 0.6 else
                "these two don't move closely together, which helps with "
                "diversification."
            )
            text = (
                f"{a}-{b} correlation over the last 30 days: {corr:.2f} "
                f"({strength} {direction} correlation) -- {diversification_note}"
            )
            chunks.append(Chunk(id=f"corr_{a}_{b}", text=text))
    return chunks


# ------------------------------------------------------------------------ #
# Step 3b: turn news headlines into chunks (individual + weekly digests)
# ------------------------------------------------------------------------ #

def build_news_headline_chunks(symbol: str, posts: list[dict]) -> list[Chunk]:
    """One chunk per headline. Precise for specific questions ("what
    happened with the SOL ETF filing") since nothing is compressed away."""
    chunks = []
    for i, post in enumerate(posts):
        text = (
            f"{symbol} news ({post['date']}, source: {post.get('source', 'unknown')}): "
            f"{post['title']}"
        )
        chunks.append(Chunk(id=f"{symbol}_news_{i}", text=text))
    return chunks


def build_news_weekly_chunks(
    symbol: str, posts: list[dict], chat: DualProviderChat
) -> list[Chunk]:
    """Group headlines into 7-day buckets (relative to the earliest post)
    and ask the model for a short thematic digest of each week. This is the
    "analyze the news" step: fewer, higher-signal chunks than one-per-headline
    alone, useful for broad questions like "how has sentiment been this month".
    """
    if not posts:
        return []

    posts_sorted = sorted(posts, key=lambda p: p["date"])
    start_date = datetime_from_iso(posts_sorted[0]["date"])

    buckets: dict[int, list[dict]] = {}
    for post in posts_sorted:
        offset_days = (datetime_from_iso(post["date"]) - start_date).days
        week_num = offset_days // 7 + 1
        buckets.setdefault(week_num, []).append(post)

    chunks = []
    for week_num, week_posts in sorted(buckets.items()):
        print(f"  Summarizing {symbol} news, week {week_num}/{len(buckets)}...")
        headlines = "\n".join(f"- ({p['date']}) {p['title']}" for p in week_posts)
        prompt = (
            f"Summarize the following {symbol} news headlines from one week "
            f"into 2-3 sentences, focused on the main themes or events "
            f"(e.g. regulation, ETF flows, network upgrades, exchange "
            f"listings, macro sentiment). Do not invent details beyond what "
            f"the headlines imply.\n\n{headlines}"
        )
        try:
            summary = chat.complete(
                [{"role": "user", "content": prompt}], temperature=0.3
            ).strip()
        except Exception:
            # Summarization is a nice-to-have; fall back to a plain list of
            # headlines rather than dropping the week's news entirely.
            summary = "; ".join(p["title"] for p in week_posts[:5])

        date_range = f"{week_posts[0]['date']} to {week_posts[-1]['date']}"
        text = f"{symbol} news digest, week {week_num} ({date_range}): {summary}"
        chunks.append(Chunk(id=f"{symbol}_news_week{week_num}", text=text))

    return chunks


def datetime_from_iso(date_str: str):
    from datetime import datetime

    return datetime.strptime(date_str, "%Y-%m-%d")


def build_all_chunks(chat: Optional[DualProviderChat] = None) -> list[Chunk]:
    """Load every tracked symbol's raw data and build the full chunk set
    (price chunks always; news chunks too if data/news_raw/ has data and a
    DualProviderChat is provided for weekly-digest summarization)."""
    chunks: list[Chunk] = []
    all_returns: dict[str, list[float]] = {}

    print("Building price chunks...")
    for symbol in SYMBOLS:
        daily = load_daily(symbol)
        returns = daily_returns(daily)
        all_returns[symbol] = returns

        chunks.append(build_overview_chunk(symbol, daily, returns))
        chunks.extend(build_weekly_chunks(symbol, daily))
    print(f"  {len(chunks)} price chunks so far (overview + weekly per coin)")

    chunks.extend(build_correlation_chunks(all_returns))

    for symbol in SYMBOLS:
        posts = load_news(symbol)
        if not posts:
            print(f"No news data for {symbol} (run news_data.py to add it) -- skipping.")
            continue
        headline_chunks = build_news_headline_chunks(symbol, posts)
        chunks.extend(headline_chunks)
        print(f"Added {len(headline_chunks)} {symbol} headline chunks.")
        if chat is not None:
            chunks.extend(build_news_weekly_chunks(symbol, posts, chat))

    return chunks


# ------------------------------------------------------------------------ #
# Step 4: embed and persist
# ------------------------------------------------------------------------ #

def embed_chunks(chunks: list[Chunk], client: genai.Client) -> None:
    """Embed every chunk in place (sets chunk.embedding). This is one API
    call per chunk with no built-in concurrency, so it's the slowest part
    of the build -- printing progress every few chunks makes it obvious
    the script is actually working rather than stuck. Always uses Gemini
    (see module docstring for why)."""
    total = len(chunks)
    print(f"Embedding {total} chunks (one API call each, this is the slow part)...")
    for i, chunk in enumerate(chunks, start=1):
        result = client.models.embed_content(model=EMBEDDING_MODEL, contents=chunk.text)
        chunk.embedding = _embedding_vector(result)
        if i % 5 == 0 or i == total:
            print(f"  Embedded {i}/{total}")


def save_store(chunks: list[Chunk]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps([asdict(c) for c in chunks], indent=2))


def build_and_save(
    gemini_api_key: Optional[str] = None,
    groq_api_key: Optional[str] = None,
    cerebras_api_key: Optional[str] = None,
) -> int:
    """Full pipeline: load raw data -> compute stats / summarize news ->
    build text chunks -> embed -> save to disk. Returns the number of
    chunks written. Embeddings always use Gemini; news-digest
    summarization uses Groq/Cerebras if at least one of those keys is
    available (set via args or GROQ_API_KEY/CEREBRAS_API_KEY env vars),
    and falls back to skipping summarization (plain headline chunks still
    get built) if neither is set."""
    embed_client = genai.Client(api_key=gemini_api_key or os.environ.get("GEMINI_API_KEY"))

    chat = None
    try:
        chat = DualProviderChat(groq_api_key=groq_api_key, cerebras_api_key=cerebras_api_key)
    except ValueError:
        print(
            "No GROQ_API_KEY or CEREBRAS_API_KEY set -- skipping weekly news-digest "
            "summarization (individual headline chunks are unaffected)."
        )

    chunks = build_all_chunks(chat=chat)
    embed_chunks(chunks, embed_client)
    save_store(chunks)
    return len(chunks)


# ------------------------------------------------------------------------ #
# Step 5: retrieval at query time (used by chat_engine.py)
# ------------------------------------------------------------------------ #

class KnowledgeBase:
    """Loads a pre-built, pre-embedded knowledge store from disk and answers
    similarity queries against it. Build it once with `python
    knowledge_base.py`, then load it cheaply at chat-engine startup --
    querying costs one embedding call plus in-memory cosine similarity."""

    def __init__(self, client: genai.Client, store_path: Path = STORE_PATH):
        if not store_path.exists():
            raise FileNotFoundError(
                f"No knowledge store at {store_path}. Run "
                f"`python knowledge_base.py` first to build one."
            )
        self._client = client
        raw = json.loads(store_path.read_text())
        self._chunks = [Chunk(**c) for c in raw]

    def __len__(self) -> int:
        return len(self._chunks)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def retrieve(self, query: str, top_k: int = 6) -> list[str]:
        """Return the top_k chunk texts most relevant to the query. Returns
        an empty list (never raises) if the embedding call fails, so a RAG
        outage degrades gracefully instead of breaking the chat."""
        try:
            result = self._client.models.embed_content(model=EMBEDDING_MODEL, contents=query)
            query_vec = _embedding_vector(result)
        except Exception:
            return []

        scored = [
            (self._cosine(query_vec, c.embedding), c.text)
            for c in self._chunks
            if c.embedding
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [text for _, text in scored[:top_k]]


if __name__ == "__main__":
    n = build_and_save()
    print(f"Built and saved {n} knowledge chunks to {STORE_PATH}")