"""Gemini 适配器：直接用 REST，避免额外 SDK 依赖。

文档：POST /v1beta/models/{model}:generateContent
"""

from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY 未配置")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _to_gemini(self, messages: list[dict]) -> tuple[dict | None, list[dict]]:
        """system 抽取成 systemInstruction，其余映射成 user/model。"""
        system_parts: list[str] = []
        contents: list[dict] = []
        for m in messages:
            role = m.get("role")
            text = m.get("content", "")
            if role == "system":
                system_parts.append(text)
            else:
                contents.append(
                    {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
                )
        system = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
        return system, contents

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        system, contents = self._to_gemini(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                **({"maxOutputTokens": max_tokens} if max_tokens else {}),
            },
        }
        if system:
            payload["systemInstruction"] = system

        url = f"{API_ROOT}/models/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上 Gemini：{type(exc).__name__}") from exc

        if resp.status_code == 429:
            raise LLMError("Gemini 限流（429）")
        if resp.status_code != 200:
            raise LLMError(f"Gemini 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("Gemini 没有返回候选结果")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise LLMError("Gemini 返回了空内容")
        return text
