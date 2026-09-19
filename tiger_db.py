"""
tiger_db.py
===========
TimescaleDB (Tiger Data) & Cloud PostgreSQL Persistence:
- crypto_metrics hypertable for real-time regression telemetry
- User authentication and persistent chat session storage
"""

import json
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment credentials
env_path = Path(__file__).resolve().parent / "tiger-cloud-tara-db-credentials.env"
load_dotenv(dotenv_path=env_path)
load_dotenv()

DB_URL = os.getenv("TIMESCALE_SERVICE_URL") or os.getenv("DATABASE_URL") or os.getenv("TIMESCALE_URL")

if not DB_URL:
    DB_URL = "postgres://tsdbadmin:d2b3e499o83tozfa@ge1kb3jidi.kklimkxesd.tsdb.cloud.timescale.com:39876/tsdb?sslmode=require"


def get_connection():
    """Establishes connection to Timescale Cloud."""
    return psycopg2.connect(DB_URL)


def init_database():
    """Initializes tables and provisions the crypto_metrics hypertable."""
    print("Connecting to Tiger Data (Timescale Cloud)...")
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_portfolios (
            user_name TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            buy_price DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            last_updated TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS crypto_metrics (
            time TIMESTAMPTZ NOT NULL,
            symbol TEXT NOT NULL,
            price DOUBLE PRECISION,
            trend_price DOUBLE PRECISION,
            percent_diff DOUBLE PRECISION,
            daily_growth DOUBLE PRECISION,
            position TEXT
        );
        """)

        try:
            cur.execute("SELECT create_hypertable('crypto_metrics', 'time', if_not_exists => TRUE);")
            print("✓ Successfully provisioned 'crypto_metrics' as a Tiger Data Hypertable!")
        except Exception as e:
            print(f"Hypertable notice: {e}")

        conn.commit()
        cur.close()
        conn.close()

        # Initialize authentication and chat history tables
        init_auth_tables()
        print("✓ All Tiger Data tables initialized successfully!")
    except Exception as err:
        print(f"Tiger Data connection notice: {err}")


def init_auth_tables():
    """Provisions tables for user authentication and chat history."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_chat_sessions (
        chat_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        messages JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


def save_user_chat_session(username: str, chat_id: str, title: str, messages: list):
    """Saves or updates a user's conversation history in the cloud database."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        query = """
        INSERT INTO user_chat_sessions (chat_id, username, title, messages, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (chat_id) DO UPDATE
        SET title = EXCLUDED.title,
            messages = EXCLUDED.messages,
            updated_at = NOW();
        """
        cur.execute(query, (chat_id, username, title, json.dumps(messages)))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error saving chat to database: {e}")


def load_user_chat_sessions(username: str) -> list:
    """Retrieves all previous chat sessions for a user safely."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
        SELECT chat_id, title, messages, updated_at
        FROM user_chat_sessions
        WHERE username = %s
        ORDER BY updated_at DESC;
        """
        cur.execute(query, (username,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for r in rows:
            results.append({
                "chat_id": r["chat_id"],
                "title": r["title"],
                "messages": r["messages"],
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else ""
            })
        return results
    except Exception as e:
        print(f"Notice: Initializing tables due to query notice: {e}")
        try:
            init_auth_tables()
        except Exception:
            pass
        return []


def log_crypto_metric(data: dict):
    """Inserts a real-time quantitative regression tick into the hypertable."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        query = """
        INSERT INTO crypto_metrics (time, symbol, price, trend_price, percent_diff, daily_growth, position)
        VALUES (NOW(), %s, %s, %s, %s, %s, %s);
        """
        cur.execute(query, (
            str(data['symbol']),
            float(data['current_price']),
            float(data['trend_price_today']),
            float(data['percent_diff']),
            float(data['daily_growth_percent']),
            str(data['position'])
        ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✓ Successfully logged {data['symbol']} time-series tick to Tiger Data!")
    except Exception as e:
        print(f"Notice: Could not log tick to Tiger Data: {e}")


def get_recent_metrics(limit: int = 10):
    """Fetches recent ticks from the hypertable for telemetry feeds."""
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = """
        SELECT time, symbol, price, trend_price, percent_diff, daily_growth, position
        FROM crypto_metrics
        ORDER BY time DESC
        LIMIT %s;
        """
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for r in rows:
            results.append({
                "time": r["time"].strftime("%Y-%m-%d %H:%M:%S UTC") if r.get("time") else "",
                "symbol": r["symbol"],
                "price": round(float(r["price"]), 2),
                "trend_price": round(float(r["trend_price"]), 2),
                "percent_diff": round(float(r["percent_diff"]), 2),
                "daily_growth": round(float(r["daily_growth"]), 2),
                "position": r["position"]
            })
        return results
    except Exception as err:
        print(f"Tiger DB query error: {err}")
        return []


if __name__ == "__main__":
    init_database()