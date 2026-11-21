"""DeepSeek 适配器（OpenAI 兼容协议）。

国内可直连，不需要代理；作为 Gemini 之外的另一个可替换选择。
"""

from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.deepseek.com"


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = DEFAULT_BASE,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LLMError("DEEPSEEK_API_KEY 未配置")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上 DeepSeek：{type(exc).__name__}") from exc

        if resp.status_code == 429:
            raise LLMError("DeepSeek 限流（429）")
        if resp.status_code != 200:
            raise LLMError(f"DeepSeek 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("DeepSeek 没有返回结果")
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMError("DeepSeek 返回了空内容")
        return text
