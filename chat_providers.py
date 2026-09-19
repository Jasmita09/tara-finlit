"""
chat_providers.py
=================
Multi-Provider LLM Client for Project Tara:
- Primary: Groq (using active "openai/gpt-oss-20b")
- Secondary / Failover: Google Gemini (using active "gemini-2.5-flash")
"""

from __future__ import annotations

import os
from typing import Optional
from openai import OpenAI

GROQ_MODEL = "openai/gpt-oss-20b"
GEMINI_MODEL = "gemini-2.5-flash"


class DualProviderChat:
    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        cerebras_api_key: Optional[str] = None,
    ):
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.last_provider_used: Optional[str] = None

    def complete(self, messages: list[dict], temperature: float = 0.7) -> str:
        """
        Sends the conversation to Groq first. If Groq encounters any rate limit
        or model error, it automatically fails over to Google Gemini.
        """
        errors = []

        # 1. Try Groq Primary
        if self.groq_api_key:
            try:
                client = OpenAI(
                    api_key=self.groq_api_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    temperature=temperature,
                )
                self.last_provider_used = f"Groq ({GROQ_MODEL})"
                return response.choices[0].message.content or ""
            except Exception as e:
                errors.append(f"Groq: {str(e)}")

        # 2. Fallback to Google Gemini
        if self.gemini_api_key:
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_api_key)
                
                # Format message list into a clean prompt string for Gemini
                prompt_lines = []
                for m in messages:
                    role_label = "System Instructions" if m["role"] == "system" else ("User" if m["role"] == "user" else "Tara")
                    prompt_lines.append(f"{role_label}: {m['content']}")
                full_prompt = "\n\n".join(prompt_lines)

                # Try Gemini 2.5 Flash, or 2.0 Flash as backup
                for g_model in [GEMINI_MODEL, "gemini-2.0-flash"]:
                    try:
                        response = client.models.generate_content(
                            model=g_model,
                            contents=full_prompt,
                        )
                        if response and response.text:
                            self.last_provider_used = f"Google Gemini ({g_model})"
                            return response.text
                    except Exception as model_err:
                        errors.append(f"Gemini [{g_model}]: {str(model_err)}")
            except Exception as genai_err:
                errors.append(f"Gemini client: {str(genai_err)}")

        raise RuntimeError(f"All chat providers failed. Details: {'; '.join(errors)}")
    