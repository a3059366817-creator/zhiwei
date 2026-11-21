"""记忆提取：让模型提出候选，但不给它写库的权力。

模型输出必须是 JSON；解析失败就当作「本轮没有候选」，绝不猜测。
"""

from __future__ import annotations

import json
import logging

from app.llm.base import LLMError
from app.llm.router import LLMRouter
from app.memory.schemas import ExtractionResult

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """你是一个信息提取器。从「用户这句话」里找出**值得长期记住**的信息。

只在满足以下条件时才提出候选：
1. 是用户自己说出的、明确的事实或偏好；
2. 它对未来对话有长期价值（兴趣、身份、项目、习惯、关系、明确偏好）；
3. 不是一次性的闲聊、情绪波动、反问、玩笑。

绝对不要：
- 不要推测。用户没说的工作、关系、感受，一个都不要写。
- 不要把「我问你问题」当成事实。
- 不要记录密码、验证码、身份证号、银行卡号、API Key 等凭证信息。

**介绍人物时必须归到 relationship**：
只要这句话在介绍某个人（「我妈…」「我室友叫小林…」「我朋友王强…」「我导师姓陈…」），
就必须用 category=relationship，并把 person_name（怎么称呼）和 relation_type（什么关系）填上，
不要拆成 profile 或 preference。

类别只能是：preference（偏好）/ profile（身份兴趣技能）/ experience（经历项目）
/ relationship（人物关系）/ context（近期状态）。
敏感程度：涉及收入、健康、感情、家庭矛盾、住址、证件的，标 sensitive。

输出 JSON，不要任何解释：
{"candidates":[{"category":"preference","content":"一句话陈述，用「他」作主语","reason":"为什么值得记","sensitivity":"normal"}]}

如果是人物关系（category=relationship），额外补两个字段：
{"category":"relationship","content":"他妈妈下个月生日","person_name":"妈妈","relation_type":"母亲","reason":"家人日程"}
- person_name：用户怎么称呼这个人（原词）
- relation_type：关系（母亲/父亲/朋友/同事/导师…），不确定就写「未明确」

如果没有值得记的内容，输出 {"candidates":[]}。

用户这句话：
"""


def _extract_json_object(text: str) -> dict | None:
    """从模型输出里抠出第一个完整 JSON 对象（容忍 ```json 包裹）。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if "```" in s[3:] else s[3:]
        s = s.removeprefix("json").strip()
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class MemoryExtractor:
    def __init__(self, llm: LLMRouter) -> None:
        self.llm = llm

    async def extract(self, user_text: str) -> ExtractionResult:
        messages = [
            {"role": "system", "content": "你只输出 JSON，不输出任何其他内容。"},
            {"role": "user", "content": EXTRACTION_PROMPT + user_text},
        ]
        try:
            raw, _model = await self.llm.chat(messages, temperature=0.1, max_tokens=700)
        except LLMError as exc:
            logger.warning("记忆提取失败（模型层）：%s", exc)
            return ExtractionResult()

        data = _extract_json_object(raw)
        if data is None:
            logger.warning("记忆提取返回的不是合法 JSON，已忽略")
            return ExtractionResult()

        try:
            return ExtractionResult.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆候选结构校验失败：%s", exc)
            return ExtractionResult()
