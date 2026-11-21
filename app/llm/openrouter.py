"""OpenRouter 适配器（OpenAI 兼容协议），作为 Gemini 的备用。"""

from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LLMError("OPENROUTER_API_KEY 未配置")
        if not model:
            raise LLMError("OPENROUTER_MODEL 未配置")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(API_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上 OpenRouter：{type(exc).__name__}") from exc

        if resp.status_code != 200:
            raise LLMError(f"OpenRouter 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("OpenRouter 没有返回结果")
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMError("OpenRouter 返回了空内容")
        return text
