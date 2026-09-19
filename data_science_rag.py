"""
data_science_rag.py
===================
Quantitative Engine for Project Tara:
- Dynamic symbol resolution (maps "Apple" -> "AAPL", "Google" -> "GOOGL")
- 30-Day Logarithmic Regression: ln(y) = mx + b
- Quantitative Market Radar: scans in-demand momentum vs. discount opportunities
"""

import yfinance as yf
import numpy as np
import requests

# Common company names & crypto nicknames mapped to official tickers
COMMON_TICKER_MAP = {
    "APPLE": "AAPL",
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "MICROSOFT": "MSFT",
    "AMAZON": "AMZN",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "META": "META",
    "FACEBOOK": "META",
    "NETFLIX": "NFLX",
    "AMD": "AMD",
    "BITCOIN": "BTC-USD",
    "BTC": "BTC-USD",
    "ETHEREUM": "ETH-USD",
    "ETH": "ETH-USD",
    "SOLANA": "SOL-USD",
    "SOL": "SOL-USD",
    "DOGECOIN": "DOGE-USD",
    "DOGE": "DOGE-USD",
    "RIVIAN": "RIVN",
    "PALANTIR": "PLTR",
    "COINBASE": "COIN",
    "DISNEY": "DIS",
    "SPY": "SPY",
    "QQQ": "QQQ"
}

def resolve_ticker(query_sym: str) -> str:
    """Resolves names like 'APPLE' or 'GOOGLE' to 'AAPL' and 'GOOGL'."""
    clean = query_sym.upper().strip()
    if clean in COMMON_TICKER_MAP:
        return COMMON_TICKER_MAP[clean]
    
    # Optional: Fast Yahoo Finance search query fallback for unknown company names
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={clean}&quotesCount=1"
        res = requests.get(url, headers={"User-Agent": "TaraBot/1.0"}, timeout=2).json()
        quotes = res.get("quotes", [])
        if quotes and "symbol" in quotes[0]:
            return quotes[0]["symbol"]
    except Exception:
        pass

    return clean


def get_market_data_and_rag_context(symbol: str, buy_price: float = 0.0, amount: float = 1.0):
    raw_sym = symbol.upper().strip()
    ticker_symbol = resolve_ticker(raw_sym)
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="30d", interval="1d")
        
        # If standard symbol failed, try with -USD for general crypto
        if (df.empty or len(df) < 5) and not ticker_symbol.endswith("-USD"):
            alt_ticker = f"{raw_sym}-USD"
            alt_df = yf.Ticker(alt_ticker).history(period="30d", interval="1d")
            if not alt_df.empty and len(alt_df) >= 5:
                ticker_symbol = alt_ticker
                df = alt_df

        if df.empty or len(df) < 5:
            return None

        closes = df["Close"].values
        days = np.arange(len(closes))
        log_closes = np.log(closes)

        # 30-Day Logarithmic Regression: ln(y) = mx + b
        slope, y_intercept = np.polyfit(days, log_closes, 1)
        log_trendline = slope * days + y_intercept
        trendline = np.exp(log_trendline)

        current_price = round(float(closes[-1]), 2)
        trend_price_today = round(float(trendline[-1]), 2)
        dollar_diff = round(current_price - trend_price_today, 2)
        percent_diff = round((dollar_diff / trend_price_today) * 100, 1)
        position = "ABOVE" if current_price >= trend_price_today else "BELOW"
        daily_growth_percent = round((np.exp(slope) - 1) * 100, 2)

        # Portfolio P&L calculations
        total_invested = round(buy_price * amount, 2) if buy_price > 0 else 0.0
        current_value = round(current_price * amount, 2) if buy_price > 0 else 0.0
        pnl_dollar = round(current_value - total_invested, 2) if buy_price > 0 else 0.0
        pnl_percent = round(((current_price - buy_price) / buy_price) * 100, 1) if buy_price > 0 else 0.0

        dates = [d.strftime("%b %d") if hasattr(d, "strftime") else str(d)[:10] for d in df.index]
        chart_points = [
            {"date": d, "actual": round(float(a), 2), "trend": round(float(t), 2)}
            for d, a, t in zip(dates, closes, trendline)
        ]

        clean_name = raw_sym
        try:
            info = ticker.info or {}
            clean_name = info.get("shortName") or info.get("longName") or raw_sym
        except Exception:
            clean_name = raw_sym

        return {
            "symbol": ticker_symbol.replace("-USD", ""),
            "name": clean_name,
            "current_price": current_price,
            "trend_price_today": trend_price_today,
            "dollar_diff": dollar_diff,
            "percent_diff": percent_diff,
            "position": position,
            "daily_growth_percent": daily_growth_percent,
            "user_buy_price": buy_price,
            "user_amount": amount,
            "total_invested": total_invested,
            "current_value": current_value,
            "pnl_dollar": pnl_dollar,
            "pnl_percent": pnl_percent,
            "chart_points": chart_points,
            "start_date": dates[0],
            "mid_date": dates[len(dates)//2],
            "end_date": dates[-1]
        }
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None


def get_market_radar_scan():
    """Scans popular assets and ranks them by Momentum vs. Recovery Value."""
    watchlist = ["NVDA", "TSLA", "AAPL", "MSFT", "AMD", "BTC-USD", "SOL-USD"]
    results = []

    for sym in watchlist:
        try:
            t = yf.Ticker(sym)
            df = t.history(period="30d", interval="1d")
            if len(df) < 10:
                continue
            closes = df["Close"].values
            days = np.arange(len(closes))
            slope, intercept = np.polyfit(days, np.log(closes), 1)
            trend_today = np.exp(slope * days[-1] + intercept)
            curr = closes[-1]
            diff_pct = round(((curr - trend_today) / trend_today) * 100, 1)

            results.append({
                "symbol": sym.replace("-USD", ""),
                "price": round(float(curr), 2),
                "trend": round(float(trend_today), 2),
                "diff_percent": diff_pct,
                "status": "High Demand / Momentum" if diff_pct > 0 else "Discount / Rebound Opportunity"
            })
        except Exception:
            continue

    # Sort: Highest momentum first
    results.sort(key=lambda x: x["diff_percent"], reverse=True)
    return results