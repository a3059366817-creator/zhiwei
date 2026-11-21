"""模型层抽象：业务代码只依赖这个接口，不依赖任何具体厂商。"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


class ChatMessage(dict):
    """一条对话消息：{"role": ..., "content": ...}"""

    def __init__(self, role: Role, content: str) -> None:
        super().__init__(role=role, content=content)


class LLMError(RuntimeError):
    """模型调用失败（网络、限流、鉴权、返回格式异常）。"""


@runtime_checkable
class LLMProvider(Protocol):
    """所有模型适配器都必须满足的接口。"""

    name: str

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int | None = None,
    ) -> str:
        """返回模型回复的纯文本；失败必须抛 LLMError。"""
        ...
