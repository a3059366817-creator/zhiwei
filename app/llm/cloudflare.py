"""Cloudflare Workers AI 适配器。

端点：POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}
鉴权：Authorization: Bearer <API_TOKEN>
返回：{"result": {"response": "..."}, "success": true}

注意：
- account_id 是必须的（在 URL 里），不是密钥的一部分；
- 免费额度按 neuron 计算，超了会返回 429 或 400，这里统一转成 LLMError 让路由切备用。
"""

from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct"


def _extract_text(result: object) -> str:
    """兼容两种返回：{response: "..."} 和 OpenAI 风格 {choices:[{message:{content}}]}。"""
    if isinstance(result, str):
        return result.strip()
    if not isinstance(result, dict):
        return ""

    resp = result.get("response")
    if isinstance(resp, str) and resp.strip():
        return resp.strip()

    choices = result.get("choices") or []
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        content = (first.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


class CloudflareProvider:
    name = "cloudflare"

    def __init__(
        self,
        api_token: str,
        account_id: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE,
        # Workers AI 偶发几十秒的排队，超时就交给备用模型，别让用户干等
        timeout: float = 25.0,
    ) -> None:
        if not api_token:
            raise LLMError("CLOUDFLARE_API_TOKEN 未配置")
        if not account_id:
            raise LLMError("CLOUDFLARE_ACCOUNT_ID 未配置（在 Cloudflare 控制台右侧栏可以复制）")
        self.api_token = api_token
        self.account_id = account_id
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _url(self) -> str:
        return f"{self.base_url}/accounts/{self.account_id}/ai/run/{self.model}"

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        }
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self._url(), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上 Cloudflare Workers AI：{type(exc).__name__}") from exc

        if resp.status_code == 429:
            raise LLMError("Cloudflare 免费额度/速率限制（429）")
        if resp.status_code in (401, 403):
            raise LLMError("Cloudflare 鉴权失败：检查 API Token 与账户 ID 是否匹配")
        if resp.status_code == 404:
            raise LLMError(f"Cloudflare 找不到模型 {self.model}（可能未开通或名字写错）")
        if resp.status_code != 200:
            raise LLMError(f"Cloudflare 返回 {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError("Cloudflare 返回的不是 JSON") from exc

        if not data.get("success", True):
            errors = data.get("errors") or []
            raise LLMError(f"Cloudflare 业务错误：{errors[:1]}")

        result = data.get("result") or {}
        text = _extract_text(result)
        if not text:
            raise LLMError("Cloudflare 返回了空内容")
        return text
