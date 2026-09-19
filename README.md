# 🌟 Project Tara

> **Empathetic, Quantitative Financial Literacy & Autonomous On-Chain Agent**  
> *Built for HackHer GSU 2026 by Jasmita Iragam*

[![Solana Devnet](https://img.shields.io/badge/Solana-Devnet-14F195?logo=solana&logoColor=black)](https://solana.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Turbo_v2.5-FF6B6B?logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![TimescaleDB](https://img.shields.io/badge/Database-TimescaleDB-FDB515?logo=postgresql&logoColor=white)](https://www.timescale.com)
[![Groq & Gemini](https://img.shields.io/badge/Dual_LLM-Groq_%7C_Gemini-blue)](https://groq.com)

---

## 🧭 Inspiration & Mission

In ancient Sanskrit, **Tara** means *"star"* or *"the one who guides across."* Historically, navigators looked to the stars to chart safe passage through turbulent, unpredictable oceans. 

Modern financial and cryptocurrency markets represent that exact same stormy sea: volatile, jargon-heavy, and deeply intimidating. According to research from Vanguard, **27% of women cite a lack of confidence and knowledge as their primary barrier to investing**, compared to 19% of men.

Furthermore, many beginners are never taught the critical distinction between:
- **Trading:** Short-term, high-stress speculation that frequently amounts to gambling.
- **Investing:** Disciplined, patient, long-term compounding.

Even common tools like **401(k)s and IRAs are widely misunderstood as "stocks"—when they are actually tax-advantaged "baskets" or containers holding investments.**

**Project Tara** eliminates the intimidation barrier by pairing human-centric Socratic mentorship with objective data science and autonomous Web3 execution.

---

## ⚡ Core Features

### 1. Socratic Voice Mentor & Real-Time Audio Visualizer
- **ElevenLabs Turbo v2.5:** Conversational voice synthesis using the empathetic *Sarah* voice (`EXAVITQu4vr4xnSDxMaL`) with a custom markdown-sanitizing regex filter so markdown formatting syntax is never read aloud.
- **Browser-Native Web Audio API:** Client-side `AudioContext` and `AnalyserNode` tracking microphone Fast Fourier Transform (FFT) amplitude at 60 FPS, pulsing Tara's glowing mentor orb without server latency.
- **2.2-Second Speech Debounce:** Web Speech API listening logic engineered to give beginners natural breathing room to pause without being cut off mid-sentence.

### 2. Quantitative 30-Day Fair-Value Trendline
- Rather than providing black-box predictions, Tara computes an objective **30-day logarithmic regression**.
- Translates Wall Street jargon into friendly terms:
  - *30D Logarithmic Window* $\rightarrow$ **30-Day Healthy Trendline**
  - *30D Baseline* $\rightarrow$ **Typical 30-Day Fair Price**
  - *Trade Signals* $\rightarrow$ **3 Simple Paths Forward**
- Highlights whether an asset is overbought on momentum or trading at a statistical fair-value discount.

### 3. Frictionless Sessions with TigerData (TimescaleDB)
- **Zero-Password Onboarding:** Users simply input a username handle (e.g., `sarah_invests` or `Hello_Jas`).
- **Stateless Cloud Persistence:** TimescaleDB / PostgreSQL automatically pulls prior chat threads, quantitative metrics, and regression cards. Switching usernames instantly switches sessions; typing the original username restores all history.

### 4. Autonomous Solana Agent & MCP Tool Execution
- Built using the **Model Context Protocol (MCP)** to allow LLMs to invoke real financial tools.
- **Persistent Keypairs:** Deterministic agent keypair (`solana_agent_key.json`) and dedicated **Tara DCA Savings Vault** (`solana_vault_key.json`).
- **1-Click Autonomous DCA:** Signs Ed25519 transfers on Solana Devnet via Python `solders`.
- **Verifiable SPL Memos:** Records Tara's mathematical reasoning and fair-value baseline directly to the blockchain via the Solana SPL Memo Program for auditability.

---

## 🏗️ System Architecture

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND INTERFACE (Client SPA)                           │
│                                                                                        │
│   ┌──────────────────────────────────────────┐   ┌─────────────────────────────────┐   │
│   │        Basic Layout & Chat Shell         │   │   60 FPS Web Audio Visualizer   │   │
│   │      (Teammate Initial Prototype)        │   │    & Canvas Regression Charts   │   │
│   │                                          │   │    (Engineered & Wired Solo)    │   │
│   └────────────────────┬─────────────────────┘   └────────────────┬────────────────┘   │
└────────────────────────┼──────────────────────────────────────────┼────────────────────┘
                         │ User Prompt / Input                      │ Real-time Mic RMS
                         ▼                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│              UNIFIED BACKEND ORCHESTRATION LAYER (Engineered & Integrated Solo)         │
│                                                                                        │
│                                Flask REST & JSON-RPC Gateway                           │
│                                              │                                         │
│                      Dual-LLM Failover Engine (Zero Downtime)                          │
│                      Groq (Llama 3 @ ~300ms)  ──[On Rate Limit/Fail]──>  Google Gemini │
│                                              │                                         │
│                                   Model Context Protocol                               │
│                                   (MCP Tool Routing Hub)                               │
└──────────────┬───────────────────────────────┼──────────────────────────────┬──────────┘
               │                               │                              │
               ▼                               ▼                              ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐ ┌─────────────────────────────┐
│     QUANTITATIVE ENGINE     │ │     SOLANA AGENT ENGINE     │ │     TIGERDATA PERSISTENCE   │
│   (Engineered Solo)         │ │   (Engineered Solo)         │ │   (Engineered Solo)         │
│                             │ │                             │ │                             │
│ • 30D Logarithmic Regression│ │ • Autonomous Keypair Signing│ │ • TimescaleDB (PostgreSQL)  │
│ • Jargon-Free Fair-Value    │ │ • Tara DCA Savings Vault    │ │ • Stateless Username Auth   │
│   Baseline Calculation      │ │ • SPL On-Chain Memos        │ │ • Instant Session Restore   │
│ • Plain-English Signals     │ │ • Live Solana Explorer Link │ │ • Chat Telemetry Logging    │
└─────────────────────────────┘ └─────────────────────────────┘ └─────────────────────────────┘
