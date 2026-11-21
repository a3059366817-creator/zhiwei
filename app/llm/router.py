"""模型路由：按配置选主模型，失败自动切备用。

业务代码只调 `router.chat()`，永远不知道背后是 Ollama / Gemini / OpenRouter。
"""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.deepseek import DeepSeekProvider
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider
from app.llm.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


def build_provider(name: str, settings: Settings):
    """按名字构造适配器；配置不全时抛 LLMError。"""
    key = (name or "").strip().lower()
    if key == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    if key == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if key == "openrouter":
        return OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
    if key == "deepseek":
        return DeepSeekProvider(
            settings.deepseek_api_key, settings.deepseek_model, settings.deepseek_base_url
        )
    raise LLMError(f"未知的模型提供方：{name}")


class LLMRouter:
    """主备模型调度。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: list = []
        for name in (settings.llm_provider, settings.llm_fallback_provider):
            if not name:
                continue
            try:
                self._providers.append(build_provider(name, settings))
            except LLMError as exc:
                logger.warning("模型 %s 初始化跳过：%s", name, exc)

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> tuple[str, str]:
        """返回 (回复文本, 实际使用的模型名)。

        全部失败时抛 LLMError，由上层决定怎么告知用户。
        """
        if not self._providers:
            raise LLMError("没有任何可用的模型提供方，请检查 .env")

        errors: list[str] = []
        for provider in self._providers:
            try:
                text = await provider.chat(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
                return text, provider.name
            except LLMError as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.warning("模型 %s 调用失败，尝试下一个：%s", provider.name, exc)
        raise LLMError("；".join(errors))
