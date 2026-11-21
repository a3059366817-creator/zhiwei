"""本地 Ollama 适配器（开发环境零成本、可离线）。"""

from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError

logger = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:8b",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_ctx": 8192,
                # 小模型容易车轱辘话，压重复
                "repeat_penalty": 1.18,
                "presence_penalty": 0.4,
                "frequency_penalty": 0.4,
                **({"num_predict": max_tokens} if max_tokens else {}),
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上本地模型（{self.base_url}）：{type(exc).__name__}") from exc

        if resp.status_code != 200:
            raise LLMError(f"ollama 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        content = (data.get("message") or {}).get("content") or ""
        content = content.strip()
        if not content:
            raise LLMError("ollama 返回了空内容")
        return content
