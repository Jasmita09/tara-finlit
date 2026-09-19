"""
Tara -- Core Chat Engine
==========================
This is the backend "algorithm" behind Tara, the stock mentor chatbot.
It is UI-agnostic: main.py drives it from the terminal for now, but a web
or mobile frontend would call the exact same TaraChatEngine class.

Handles:
  - Two conversation modes: 'learn' (education) and 'analyze' (behavior
    coaching on the user's own portfolio/trades)
  - Mode switching mid-session, with a short summary handed off so context
    isn't lost when the mode changes
  - A zero-cost keyword heuristic that *suggests* switching to analyze mode
    (it never switches automatically -- the user stays in control)
  - Optional RAG grounding: if a KnowledgeBase (see knowledge_base.py) is
    attached, every message is checked against a local BTC/ETH/SOL price +
    news corpus, and relevant chunks are injected before the model sees the
    question -- see _build_input(). With no knowledge_base, behavior is
    unchanged and answers come from the model alone.
  - Sending messages via a DualProviderChat (Groq + Cerebras, see
    chat_providers.py) and keeping a full transcript
  - A simple portfolio-CSV analysis helper for 'analyze' mode
  - Saving the session transcript to JSON, as a stand-in for later piping
    it into a real store (time-series analytics, long-term mentor memory)

Why Groq/Cerebras instead of Gemini for chat (Sept 2026): Google cut the
Gemini free tier down to just 20 requests/day across all models -- too
tight to build and demo on. Groq and Cerebras each offer free, no-card
tiers of 30 RPM / 14,400 requests/day, and combining both (see
chat_providers.DualProviderChat) roughly doubles that and adds automatic
failover. Gemini still does the embeddings for the RAG knowledge base (see
knowledge_base.py) -- that's a separate, much less rate-limited endpoint,
and keeps this project doing real work with the Gemini API.

Setup:
    pip install openai
    export GROQ_API_KEY="your-groq-key-here"          # free, no card
    export CEREBRAS_API_KEY="your-cerebras-key-here"  # free, no card
    (at least one of the two is required; both is better)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from prompts import (
    LEARN_SYSTEM_PROMPT,
    ANALYZE_SYSTEM_PROMPT,
    MODE_HANDOFF_TEMPLATE,
    MARKET_CONTEXT_TEMPLATE,
)
from knowledge_base import KnowledgeBase
from chat_providers import DualProviderChat

# How many past turns (user+assistant pairs) to keep resending as context.
# Groq/Cerebras don't offer Gemini's server-side conversation state, so we
# resend history ourselves each call -- capping it keeps token usage (and
# therefore latency and rate-limit pressure) bounded on a long session.
MAX_HISTORY_TURNS = 12


class TaraChatEngine:
    """Manages one conversation session for the Tara stock mentor.

    Modes
    -----
    'learn'   : Socratic, encouraging investing tutor.
    'analyze' : Portfolio / behavior coach. Never gives direct buy/sell orders.
    """

    VALID_MODES = ("learn", "analyze")

    # Phrases that hint the user wants portfolio/behavior analysis rather
    # than a lesson. Used only to *suggest* a mode switch -- never to force
    # one automatically.
    ANALYZE_KEYWORDS = (
        "my portfolio", "my stocks", "my holdings", "should i sell",
        "should i buy", "i panicked", "i panic sold", "i bought when",
        "review my", "analyze my", "my trade", "my account",
    )

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        cerebras_api_key: Optional[str] = None,
        mode: str = "learn",
        knowledge_base: Optional[KnowledgeBase] = None,
    ):
        self._chat = DualProviderChat(
            groq_api_key=groq_api_key, cerebras_api_key=cerebras_api_key
        )
        self.mode = self._validate_mode(mode)
        self.knowledge_base = knowledge_base  # optional RAG grounding; None = ungrounded
        self.session_log: list[dict] = []      # full transcript, every turn
        self.user_profile = {                    # grows as the user chats
            "topics_covered": [],
            "risk_tolerance": None,
            "goals": None,
        }
        # OpenAI-style message history for the CURRENT mode, seeded with
        # that mode's system prompt. Reset (with a fresh system prompt)
        # whenever the mode changes.
        self._messages: list[dict] = [
            {"role": "system", "content": self._system_prompt_for(self.mode)}
        ]

    # ------------------------------------------------------------------ #
    # Setup / mode handling
    # ------------------------------------------------------------------ #

    def _validate_mode(self, mode: str) -> str:
        mode = mode.lower().strip()
        if mode not in self.VALID_MODES:
            raise ValueError(f"mode must be one of {self.VALID_MODES}, got '{mode}'")
        return mode

    def _system_prompt_for(self, mode: str) -> str:
        return LEARN_SYSTEM_PROMPT if mode == "learn" else ANALYZE_SYSTEM_PROMPT

    def _trim_history(self) -> None:
        """Keep the system prompt plus only the most recent MAX_HISTORY_TURNS
        user/assistant pairs, so a long session doesn't grow the prompt (and
        therefore latency/cost/rate-limit pressure) without bound."""
        system_msg = self._messages[0]
        rest = self._messages[1:]
        max_messages = MAX_HISTORY_TURNS * 2
        if len(rest) > max_messages:
            rest = rest[-max_messages:]
        self._messages = [system_msg] + rest

    def suggest_mode_switch(self, user_message: str) -> Optional[str]:
        """Lightweight, zero-API-call heuristic that flags when a message
        sent in 'learn' mode looks like it's really an analyze-mode request.
        Returns a suggestion string, or None."""
        if self.mode != "learn":
            return None
        lowered = user_message.lower()
        if any(kw in lowered for kw in self.ANALYZE_KEYWORDS):
            return "This sounds like it's about your own holdings -- want to switch to /mode analyze?"
        return None

    def switch_mode(self, new_mode: str) -> str:
        """Switch modes mid-session. A short summary of the prior
        conversation is generated and replayed into the new mode's message
        history so context isn't lost."""
        new_mode = self._validate_mode(new_mode)
        if new_mode == self.mode:
            return f"Already in '{new_mode}' mode."

        summary = self._summarize_for_handoff()  # uses the OLD mode's history
        self.mode = new_mode
        self._messages = [{"role": "system", "content": self._system_prompt_for(self.mode)}]

        if summary:
            handoff = MODE_HANDOFF_TEMPLATE.format(summary=summary)
            self._messages.append({"role": "user", "content": handoff})
            try:
                reply = self._chat.complete(self._messages, temperature=0.7)
                self._messages.append({"role": "assistant", "content": reply})
            except Exception:
                pass  # priming is a nice-to-have, not worth failing the switch over

        return f"Switched to '{new_mode}' mode."

    def _summarize_for_handoff(self) -> str:
        """Ask the model for a 2-3 sentence recap before switching modes, so
        the new mode's history isn't starting cold. Cheap and short."""
        if not self.session_log:
            return ""
        try:
            request = self._messages + [{
                "role": "user",
                "content": (
                    "In 2-3 sentences, summarize what the user knows, wants, "
                    "or is worried about so far. Return only the summary, "
                    "no preamble."
                ),
            }]
            return self._chat.complete(request, temperature=0.3).strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # Core chat
    # ------------------------------------------------------------------ #

    def _build_input(self, user_message: str) -> str:
        """If a knowledge base is attached, retrieve relevant chunks and
        wrap the user's message in the grounding template; otherwise send
        the message as-is."""
        if not self.knowledge_base:
            return user_message

        chunks = self.knowledge_base.retrieve(user_message)
        if not chunks:
            return user_message

        context_block = "\n".join(f"- {c}" for c in chunks)
        return MARKET_CONTEXT_TEMPLATE.format(context=context_block, question=user_message)

    def send(self, user_message: str) -> str:
        """Send one user message in the current mode and return the reply.
        Every turn is appended to session_log for later persistence. If a
        knowledge base is attached, the message is first grounded with
        retrieved BTC/ETH/SOL price and news context (see _build_input)."""
        timestamp = datetime.now(timezone.utc).isoformat()
        augmented_input = self._build_input(user_message)
        self._messages.append({"role": "user", "content": augmented_input})

        try:
            reply = self._chat.complete(self._messages, temperature=0.7) or "[No text in response]"
            self._messages.append({"role": "assistant", "content": reply})
            self._trim_history()
        except Exception as exc:
            reply = f"[Error contacting chat providers: {exc}]"
            self._messages.pop()  # don't leave an unanswered user turn in history

        self.session_log.append(
            {
                "timestamp": timestamp,
                "mode": self.mode,
                "user": user_message,
                "mentor": reply,
            }
        )
        return reply

    # ------------------------------------------------------------------ #
    # Analyze-mode helpers
    # ------------------------------------------------------------------ #

    def analyze_portfolio_csv(self, csv_path: str) -> str:
        """Read a simple portfolio CSV (ticker, shares, avg_cost) and ask
        the model to analyze concentration/diversification. Works in either
        mode, but is intended for 'analyze'."""
        path = Path(csv_path)
        if not path.exists():
            return f"File not found: {csv_path}"

        raw = path.read_text().strip()
        if not raw:
            return "That file is empty."

        prompt = (
            "The user's portfolio (CSV: ticker, shares, avg_cost) is below.\n\n"
            f"{raw}\n\n"
            "Identify concentration risk and sector overlap using general "
            "knowledge. Do not give direct buy/sell instructions. Frame "
            "observations as questions the user should consider, and end "
            "with 2-3 reflective follow-up questions."
        )
        return self.send(prompt)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save_session(self, out_dir: str = "sessions") -> str:
        """Write the full transcript to a timestamped JSON file -- a stand-in
        for later piping this into a real store (e.g. a time-series DB for
        analytics, or a memory service for long-term mentor context)."""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = Path(out_dir) / f"session_{stamp}.json"
        filename.write_text(json.dumps(self.session_log, indent=2))
        return str(filename)