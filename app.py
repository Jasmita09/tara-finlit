"""
app.py
======
Project Tara: Unified Server
- Learn Mode: Friendly beginner Socratic investing mentor
- Analyze Mode: Real 30-day Logarithmic Regression + Plain-English Scenarios
- Universal Stock & Crypto support via yfinance
- TimescaleDB (Tiger Data) hypertable telemetry logging
- Solana Devnet Agent Skills + Portfolio CSV Ingestion
- Robinhood & Model Context Protocol (MCP) Agent Execution
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv
import requests

load_dotenv()
env_path = Path(__file__).resolve().parent / "tiger-cloud-tara-db-credentials.env"
load_dotenv(dotenv_path=env_path)

from data_science_rag import get_market_data_and_rag_context, get_market_radar_scan
from tiger_db import (
    log_crypto_metric,
    get_recent_metrics,
    save_user_chat_session,
    load_user_chat_sessions
)
from chat_engine import TaraChatEngine
from solana_agent import SolanaAgentEngine
from mcp_tools import execute_mcp_tool, MCP_TOOL_DEFINITIONS, ROBINHOOD_SANDBOX

app = Flask(__name__, template_folder='.', static_folder='.')
# Automatically ensure TimescaleDB & Auth tables exist
try:
    from tiger_db import init_database
    init_database()
except Exception as e:
    print(f"Database initialization notice: {e}")

solana_agent = SolanaAgentEngine()

try:
    engine = TaraChatEngine(mode="learn")
    print("✓ Tara Chat Engine initialized successfully!")
except Exception as e:
    print(f"Warning: Could not initialize TaraChatEngine: {e}")
    engine = None

solana_agent = SolanaAgentEngine()

try:
    engine = TaraChatEngine(mode="learn")
    print("✓ Tara Chat Engine initialized successfully!")
except Exception as e:
    print(f"Warning: Could not initialize TaraChatEngine: {e}")
    engine = None


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/telemetry', methods=['GET'])
def telemetry_endpoint():
    try:
        ticks = get_recent_metrics(limit=10)
        return jsonify({"ticks": ticks, "status": "connected"})
    except Exception as e:
        return jsonify({"error": str(e), "ticks": [], "status": "disconnected"}), 200


@app.route('/api/chat', methods=['POST'])
def chat_endpoint():
    data = request.json or {}
    user_message = data.get('message', '').strip()
    mode = data.get('mode', 'learn').lower()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if engine:
        if mode in engine.VALID_MODES and engine.mode != mode:
            engine.switch_mode(mode)

        reply = engine.send(user_message)
        return jsonify({
            "reply": reply,
            "mode": engine.mode,
            "provider": getattr(engine._chat, "last_provider_used", "Groq/Gemini")
        })
    else:
        return jsonify({
            "reply": "Chat Engine is currently starting up or keys are being checked.",
            "mode": mode
        })


@app.route('/api/analyze', methods=['POST'])
def analyze_endpoint():
    data = request.json or {}
    symbol = str(data.get('symbol', 'BTC')).upper().strip()

    try:
        buy_price = float(data.get('buy_price') or 0.0)
    except (ValueError, TypeError):
        buy_price = 0.0

    try:
        amount = float(data.get('amount') or 1.0)
    except (ValueError, TypeError):
        amount = 1.0

    quant_data = get_market_data_and_rag_context(symbol=symbol, buy_price=buy_price, amount=amount)

    if not quant_data:
        return jsonify({
            "error": f"I couldn't find market data for '{symbol}'. Please double-check the ticker symbol (for example: NVDA, AAPL, TSLA, BTC, ETH, or AMD)."
        }), 404

    tiger_logged = False
    try:
        log_crypto_metric(quant_data)
        tiger_logged = True
    except Exception as db_err:
        print(f"Tiger Data notice: {db_err}")

    diff = quant_data["percent_diff"]
    curr = quant_data["current_price"]
    trend = quant_data["trend_price_today"]
    pnl_pct = quant_data["pnl_percent"]
    pnl_dlr = quant_data["pnl_dollar"]

    if buy_price > 0:
        if pnl_pct < -2.0:
            headline = f"Down -{abs(pnl_pct)}% from your ${buy_price} purchase price."
            option_1 = f"Hold (Wait it Out): Keep what you have. You are down ${abs(pnl_dlr)} right now. If you still believe in {symbol} for the long run, holding lets you wait for a recovery without locking in a cash loss. Avoid selling out of fear."
            option_2 = f"Buy a Little to Lower Your Average Cost (DCA): Since {symbol} is currently ${curr} (cheaper than your ${buy_price} purchase), buying a little more now brings your average price down."
            option_3 = f"Pause & Keep Your Cash Safe: Even though {symbol} had a bounce today, it's trading above its 30-day normal price of ${trend}. Keep your cash safe on the sidelines."
            bull_point = f"{symbol} is seeing short-term buying interest today, attempting to bounce back from recent drops."
            bear_point = f"Your investment is currently underwater. Volatile assets can take weeks or months to climb back to previous highs."
        elif pnl_pct > 2.0:
            headline = f"Up +{pnl_pct}% (+${pnl_dlr}) above your ${buy_price} purchase price."
            option_1 = f"Let It Grow (Hold): You are in profit (+{pnl_pct}%). If you are investing for the next few years, just let your money compound without stressing over daily price wiggles."
            option_2 = f"Lock in a Little Cash Profit: You can sell a small slice (like 10% or 20%) to put real cash profit in your bank account while leaving the rest invested."
            option_3 = f"Protect Your Gains: Decide on a price floor where you would sell if the market reverses, ensuring you walk away with guaranteed profit."
            bull_point = "Your investment is outperforming and market momentum is in your favor."
            bear_point = "Sharp upward moves often trigger pullbacks as other investors cash out their profits."
        else:
            headline = f"Near break-even ({pnl_pct}%), trading at steady 30-day pace."
            option_1 = "Hold Your Position: Keep holding while the asset figures out its next direction."
            option_2 = "Automated Investing: Continue adding small regular amounts according to your budget."
            option_3 = "Check Your Allocation: Make sure this single asset isn't taking up too much of your total savings."
            bull_point = "Steady consolidation around fair value shows healthy, stable interest."
            bear_point = "Can break up or down depending on upcoming news and earnings."
    else:
        if diff < -5.0:
            headline = f"Trading at a {abs(diff)}% discount below its normal 30-day baseline (${trend})."
            option_1 = f"Buy for the Long Term: {symbol} is on sale compared to its normal 30-day trend. An attractive entry window."
            option_2 = "Buy in Small Bits (DCA): Buy a small amount each week to pick up the discount without trying to guess the exact bottom."
            option_3 = "Wait for a Turnaround: Keep your cash ready and wait for the price to start climbing before jumping in."
            bull_point = f"Price is statistically lower than its normal 30-day average."
            bear_point = "Prices can stay depressed if the overall market remains weak."
        elif -5.0 <= diff <= 5.0:
            headline = f"Trading right around its normal 30-day pace (${trend})."
            option_1 = f"Fair Long-Term Entry: {symbol} is priced right in line with its organic trend."
            option_2 = "Scheduled DCA: Start automated small weekly purchases to avoid worrying about daily timing."
            option_3 = "Wait and Watch: Keep your money safe for now and watch how the company performs."
            bull_point = "Balanced market interest with steady buying and selling."
            bear_point = "Could break either way depending on upcoming news."
        else:
            headline = f"Trading {diff}% higher than its normal 30-day baseline (${trend})."
            option_1 = "Hold What You Have: If you already own this, let it ride. Avoid putting in large lump sums while the price is high."
            option_2 = "Wait for a Dip: Wait for the price to cool down closer to its normal line (${trend}) for a safer buy."
            option_3 = "Rebalance: If this asset is growing into too big a piece of your portfolio, consider spreading some money."
            bull_point = f"High demand and strong buyer momentum over the last month."
            bear_point = "Assets that jump quickly often see pullbacks as traders take profits."

    return jsonify({
        "type": "quantitative_analysis",
        "symbol": quant_data["symbol"],
        "name": quant_data["name"],
        "current_price": curr,
        "trend_price": trend,
        "percent_diff": diff,
        "position": quant_data["position"],
        "daily_growth_percent": quant_data.get("daily_growth_percent", 0.0),
        "headline": headline,
        "option_1": option_1,
        "option_2": option_2,
        "option_3": option_3,
        "bull_point": bull_point,
        "bear_point": bear_point,
        "pnl_dollar": quant_data["pnl_dollar"],
        "pnl_percent": quant_data["pnl_percent"],
        "user_buy_price": quant_data["user_buy_price"],
        "user_amount": quant_data["user_amount"],
        "chart_points": quant_data["chart_points"],
        "start_date": quant_data["start_date"],
        "mid_date": quant_data["mid_date"],
        "end_date": quant_data["end_date"],
        "tiger_logged": tiger_logged
    })


@app.route('/api/market-radar', methods=['GET'])
def market_radar_endpoint():
    try:
        scan_data = get_market_radar_scan()
        return jsonify({
            "status": "success",
            "items": scan_data,
            "summary": "Assets trading significantly ABOVE baseline have strong momentum. Assets trading BELOW baseline represent statistical discounts."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/upload-portfolio', methods=['POST'])
def upload_portfolio():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    save_path = Path("temp_portfolio.csv")
    file.save(save_path)

    if engine:
        analysis = engine.analyze_portfolio_csv(str(save_path))
    else:
        analysis = "Chat engine is currently offline."

    return jsonify({"analysis": analysis})


# --- USER AUTHENTICATION & CHAT PERSISTENCE ---

@app.route('/api/auth/login', methods=['POST'])
def login_endpoint():
    try:
        data = request.json or {}
        username = data.get('username', '').strip().lower()
        if not username:
            return jsonify({"error": "Username is required"}), 400

        saved_chats = load_user_chat_sessions(username)
        return jsonify({
            "status": "success",
            "username": username,
            "chats": saved_chats,
            "solana_wallet": solana_agent.pubkey_str
        })
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


@app.route('/api/user/save-chat', methods=['POST'])
def save_chat_endpoint():
    data = request.json or {}
    username = data.get('username', 'guest')
    chat_id = data.get('chat_id')
    title = data.get('title', 'Conversation')
    messages = data.get('messages', [])

    if username != 'guest' and chat_id:
        try:
            save_user_chat_session(username, chat_id, title, messages)
            return jsonify({"status": "saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"status": "ignored"})


# --- SOLANA AGENT SKILLS (MLH SOLANA BOUNTY) ---

@app.route('/api/solana/balance', methods=['POST'])
def get_solana_balance():
    data = request.json or {}
    wallet_address = data.get("wallet", "").strip() or solana_agent.pubkey_str
    balance = solana_agent.get_balance(wallet_address)
    return jsonify({
        "wallet": wallet_address,
        "balance": balance
    })


@app.route('/api/solana/agent-dca', methods=['POST'])
def solana_agent_dca():
    """Agent Skill: Executes an on-chain Devnet DCA payment transfer."""
    data = request.json or {}
    dest_wallet = data.get('wallet') or solana_agent.vault_pubkey_str
    sol_amount = float(data.get('amount', 0.05))

    result = solana_agent.execute_agent_dca_transfer(dest_wallet, sol_amount)
    return jsonify(result)

@app.route('/api/solana/attest', methods=['POST'])
def solana_attest():
    """Agent Skill: Records mentor advice on the Solana blockchain."""
    data = request.json or {}
    symbol = data.get('symbol', 'NVDA')
    baseline = float(data.get('baseline_price', 120.0))
    advice = data.get('advice', 'Hold position and Dollar-Cost Average below baseline.')

    result = solana_agent.record_advice_on_chain(symbol, baseline, advice)
    return jsonify(result)


# --- ROBINHOOD & MCP AGENT TRADING ---

@app.route('/api/robinhood/portfolio', methods=['GET'])
def get_robinhood_portfolio():
    return jsonify(ROBINHOOD_SANDBOX)


@app.route('/api/agent/trade', methods=['POST'])
def agent_trade():
    """Agentic Trade Execution: MCP tool runner for Robinhood or Solana."""
    data = request.json or {}
    tool_name = data.get('tool_name')
    arguments = data.get('arguments', {})

    result = execute_mcp_tool(tool_name, arguments)
    return jsonify(result)


# --- ELEVENLABS NEURAL TTS ---

def clean_speech_text(text: str) -> str:
    """Removes all markdown formatting, tables, and symbols so speech sounds natural."""
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'---+', '', text)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'\|.*?\|', '', text)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


@app.route('/api/tts', methods=['POST'])
def tts_endpoint():
    """Generates warm, expressive female speech using ElevenLabs Turbo v2.5."""
    data = request.json or {}
    raw_text = data.get('text', '').strip()
    text = clean_speech_text(raw_text)

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"fallback": True, "clean_text": text}), 200

    # Sarah: Warm, empathetic young female mentor voice
    voice_id = "EXAVITQu4vr4xnSDxMaL"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }

    payload = {
        "text": text[:600],
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.38,
            "similarity_boost": 0.85,
            "style": 0.45,
            "use_speaker_boost": True
        }
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            return Response(res.content, mimetype="audio/mpeg")
        else:
            return jsonify({"fallback": True, "clean_text": text}), 200
    except Exception as e:
        return jsonify({"fallback": True, "clean_text": text}), 200


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, port=5000)