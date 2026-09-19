#!/usr/bin/env python3
"""
Tara CLI -- terminal test harness for Tara, the chat engine.

    export GROQ_API_KEY="your-key-here"       # free, no card: console.groq.com
    export CEREBRAS_API_KEY="your-key-here"   # free, no card: cloud.cerebras.ai
    export GEMINI_API_KEY="your-key-here"     # only needed for grounded (RAG) answers
    python main.py

This is a backend-only smoke test: it exercises the exact same
TaraChatEngine class that a future web or mobile frontend would call,
so anything you validate here carries straight over.

Chat runs on Groq/Cerebras (see chat_providers.py) -- at least one of
those two keys is required. Gemini is optional and only used to load the
knowledge base for grounded answers; if it's not set, Tara still chats
fine, just without RAG grounding.

If data/knowledge_store.json exists (built with `python market_data.py`
+ optionally `python news_data.py` + `python knowledge_base.py`), it's
loaded automatically so answers are grounded in real BTC/ETH/SOL price and
news data.
"""

import os
import sys

from chat_engine import TaraChatEngine
from google import genai
from knowledge_base import KnowledgeBase, STORE_PATH


HELP_TEXT = """
Commands:
  /mode learn         switch to Learn mode
  /mode analyze       switch to Analyze mode
  /portfolio <path>   analyze a portfolio CSV (ticker,shares,avg_cost)
  /kb                 show knowledge base status (loaded chunks, if any)
  /save               save this session's transcript to ./sessions/
  /help               show this message
  /quit               exit
Anything else is sent to the mentor as a normal chat message.
"""


def load_knowledge_base():
    """Try to load a pre-built knowledge store. Returns None (not an
    error) if it hasn't been built yet, or if no GEMINI_API_KEY is set --
    RAG grounding is optional, Tara still chats fine without it."""
    if not STORE_PATH.exists():
        return None
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("(GEMINI_API_KEY not set -- skipping RAG grounding, chatting ungrounded.)")
        return None
    try:
        client = genai.Client(api_key=gemini_key)
        return KnowledgeBase(client)
    except Exception as exc:
        print(f"(Could not load knowledge base: {exc})")
        return None


def main() -> None:
    print("=" * 56)
    print(" Tara -- your stock mentor (terminal test mode)")
    print("=" * 56)
    print(HELP_TEXT)

    if not os.environ.get("GROQ_API_KEY") and not os.environ.get("CEREBRAS_API_KEY"):
        print(
            "Startup error: chat needs at least one of GROQ_API_KEY or "
            "CEREBRAS_API_KEY set. Both are free, no-card signups: "
            "console.groq.com and cloud.cerebras.ai"
        )
        sys.exit(1)

    knowledge_base = load_knowledge_base()
    if knowledge_base:
        print(f"Knowledge base loaded: {len(knowledge_base)} chunks (grounded answers on).")
    else:
        print(
            "No knowledge base loaded -- answers won't be grounded in real "
            "BTC/ETH/SOL data. Run `python market_data.py` then "
            "`python knowledge_base.py` (optionally `python news_data.py` "
            "first, and GEMINI_API_KEY set) to build one."
        )

    try:
        engine = TaraChatEngine(mode="learn", knowledge_base=knowledge_base)
    except ValueError as exc:
        print(f"Startup error: {exc}")
        sys.exit(1)

    print(
        "\nTara: Hi, I'm Tara! Ask me anything to learn, or type "
        "'/mode analyze' then '/portfolio sample_portfolio.csv' to try a "
        "portfolio review.\n"
    )

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting. Bye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if handle_command(user_input, engine):
                break
            continue

        hint = engine.suggest_mode_switch(user_input)
        reply = engine.send(user_input)
        print(f"\nTara: {reply}")
        if hint:
            print(f"(hint: {hint})")
        print()


def handle_command(command: str, engine: TaraChatEngine) -> bool:
    """Returns True if the CLI loop should exit."""
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/help":
        print(HELP_TEXT)
    elif cmd == "/mode" and len(parts) > 1:
        print(engine.switch_mode(parts[1].strip()))
    elif cmd == "/portfolio" and len(parts) > 1:
        print("\nAnalyzing...\n")
        print(engine.analyze_portfolio_csv(parts[1].strip()))
    elif cmd == "/kb":
        if engine.knowledge_base:
            print(f"Knowledge base: {len(engine.knowledge_base)} chunks loaded.")
        else:
            print("No knowledge base loaded -- answers are ungrounded.")
    elif cmd == "/save":
        path = engine.save_session()
        print(f"Session saved to {path}")
    elif cmd in ("/quit", "/exit"):
        print("Exiting. Bye!")
        return True
    else:
        print("Unknown command. Type /help for options.")
    return False


if __name__ == "__main__":
    main()