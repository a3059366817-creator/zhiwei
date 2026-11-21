"""记忆相关的数据契约（Pydantic）。

模型只能产出这些结构，最终是否入库由 Python 规则决定（规格 3.3 / 关键决策 3）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class MemoryCategory(StrEnum):
    PROFILE = "profile"  # 兴趣爱好、技能、长期目标
    EXPERIENCE = "experience"  # 重要经历、项目过程、决定
    RELATIONSHIP = "relationship"  # 人物关系（必须来自用户主动介绍）
    CONTEXT = "context"  # 近期状态、当前项目、待办
    PREFERENCE = "preference"  # 明确表达的长期偏好


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class ExtractedCandidate(BaseModel):
    """模型提出的一条记忆候选。"""

    category: MemoryCategory
    content: str = Field(min_length=4, max_length=300)
    reason: str = Field(default="", max_length=200)
    sensitivity: Sensitivity = Sensitivity.NORMAL
    # 仅 relationship 类会用到：把「谁」和「什么关系」单列出来，便于结构化归档
    person_name: str | None = Field(default=None, max_length=80)
    relation_type: str | None = Field(default=None, max_length=40)

    @field_validator("person_name", "relation_type", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("content")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("sensitivity", mode="before")
    @classmethod
    def _coerce_sensitivity(cls, v: object) -> object:
        """模型经常不按枚举来（high/medium/low），统一归一，别因此丢掉整批候选。"""
        if v is None:
            return Sensitivity.NORMAL
        s = str(v).strip().lower()
        if s in {"sensitive", "high", "critical", "very_high", "敏感", "高"}:
            return Sensitivity.SENSITIVE
        if s in {"normal", "medium", "low", "普通", "低", "中"}:
            return Sensitivity.NORMAL
        return Sensitivity.NORMAL

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v: object) -> object:
        """兼容模型写中文类别或别名。"""
        if v is None:
            return MemoryCategory.CONTEXT
        s = str(v).strip().lower()
        alias = {
            "偏好": "preference",
            "兴趣": "profile",
            "身份": "profile",
            "技能": "profile",
            "经历": "experience",
            "项目": "experience",
            "关系": "relationship",
            "人物": "relationship",
            "状态": "context",
            "近期": "context",
            "contextual": "context",
        }
        return alias.get(s, s)


class ExtractionResult(BaseModel):
    candidates: list[ExtractedCandidate] = Field(default_factory=list)

    @field_validator("candidates")
    @classmethod
    def _cap(cls, v: list[ExtractedCandidate]) -> list[ExtractedCandidate]:
        return v[:5]  # 一句话最多提 5 条，防止模型发散


class Decision(StrEnum):
    AUTO_SAVE = "auto_save"  # 低风险，直接入库并告知
    CONFIRM = "confirm"  # 需要用户确认
    DROP = "drop"  # 绝不入库（密码、密钥之类）


class ReviewResult(BaseModel):
    """Python 规则的判定结果。"""

    decision: Decision
    sensitivity: Sensitivity
    reason: str
