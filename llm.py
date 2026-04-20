"""Gemini LLM helper."""

from __future__ import annotations

from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from config import settings


class GeminiClient:
    """Thin wrapper around ChatGoogleGenerativeAI with async helpers."""

    def __init__(self, app_settings=settings, temperature: float = 0.4):
        if not app_settings.google_api_key:
            raise ValueError("GEMINI_API_KEY is missing; cannot initialize Gemini client")

        self._llm = ChatGoogleGenerativeAI(
            model=app_settings.gemini_model,
            google_api_key=app_settings.google_api_key,
            temperature=temperature,
        )

    async def generate_text(self, prompt: str) -> str:
        """Generate text from Gemini as plain string."""
        response = await self._llm.ainvoke(prompt)
        content: Any = getattr(response, "content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            return "".join(str(part) for part in content)

        return str(content)
