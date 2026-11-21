"""记忆审核规则：模型只提议，Python 决定能不能存。

对应规格：
- 3.3 混合记忆机制（低风险自动保存 / 重要或敏感必须确认）
- 8.3 记忆隐私（敏感信息未经确认不能进长期记忆）
- 关键决策 5：宁可少记，也不要错记
"""

from __future__ import annotations

from app.memory.schemas import (
    Decision,
    ExtractedCandidate,
    MemoryCategory,
    ReviewResult,
    Sensitivity,
)

# 绝对不入库：凭证类信息，连候选都不生成
FORBIDDEN_KEYWORDS = (
    "密码",
    "口令",
    "验证码",
    "api key",
    "apikey",
    "token",
    "私钥",
    "助记词",
    "身份证号",
    "银行卡号",
    "信用卡",
    "cvv",
)

# 敏感：必须用户明确确认，且默认不自动保存
SENSITIVE_KEYWORDS = (
    "工资",
    "薪资",
    "收入",
    "存款",
    "负债",
    "欠款",
    "病历",
    "诊断",
    "抑郁症",
    "焦虑症",
    "手术",
    "恋爱",
    "分手",
    "离婚",
    "吵架",
    "性取向",
    "家庭矛盾",
    "身份证",
    "住址",
    "家庭住址",
    "手机号",
)

# 这些类别默认低风险，可以自动保存
LOW_RISK_CATEGORIES = {
    MemoryCategory.PREFERENCE,
    MemoryCategory.PROFILE,
    MemoryCategory.CONTEXT,
}

# 这些类别必须用户确认（关系信息尤其不能靠推断）
CONFIRM_CATEGORIES = {
    MemoryCategory.EXPERIENCE,
    MemoryCategory.RELATIONSHIP,
}


# 出现这些词就说明涉及他人，必须确认（规格 3.2C：不得凭一句话推断关系）
RELATIONSHIP_HINTS = (
    "妈",
    "母亲",
    "爸",
    "父亲",
    "哥",
    "姐",
    "弟",
    "妹",
    "爷",
    "奶",
    "外公",
    "外婆",
    "姥姥",
    "姥爷",
    "家人",
    "家里",
    "亲人",
    "亲戚",
    "长辈",
    "女朋友",
    "男朋友",
    "妻子",
    "丈夫",
    "媳妇",
    "老婆",
    "老公",
    "对象",
    "前女友",
    "前男友",
    "孩子",
    "儿子",
    "女儿",
    "宝宝",
    "娃",
    "朋友",
    "室友",
    "同事",
    "老板",
    "领导",
    "导师",
    "同学",
    "老师",
)


def _contains(text: str, words: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for w in words:
        if w.lower() in lowered:
            return w
    return None


def review(candidate: ExtractedCandidate, auto_save_enabled: bool = True) -> ReviewResult:
    """给一条候选下判定。"""
    text = f"{candidate.content} {candidate.reason}"

    forbidden = _contains(text, FORBIDDEN_KEYWORDS)
    if forbidden:
        return ReviewResult(
            decision=Decision.DROP,
            sensitivity=Sensitivity.SENSITIVE,
            reason=f"包含凭证类信息（{forbidden}），不入库",
        )

    sensitive_hit = _contains(text, SENSITIVE_KEYWORDS)
    if sensitive_hit or candidate.sensitivity == Sensitivity.SENSITIVE:
        return ReviewResult(
            decision=Decision.CONFIRM,
            sensitivity=Sensitivity.SENSITIVE,
            reason=f"涉及敏感信息（{sensitive_hit or '模型标记'}），必须确认",
        )

    if candidate.category in CONFIRM_CATEGORIES:
        return ReviewResult(
            decision=Decision.CONFIRM,
            sensitivity=Sensitivity.NORMAL,
            reason="经历/关系类信息需要确认",
        )

    # 即使模型判成「偏好」，只要提到别人也一律走确认
    person = _contains(text, RELATIONSHIP_HINTS)
    if person:
        return ReviewResult(
            decision=Decision.CONFIRM,
            sensitivity=Sensitivity.NORMAL,
            reason=f"涉及他人（{person}），需要确认",
        )

    if candidate.category in LOW_RISK_CATEGORIES:
        if not auto_save_enabled:
            return ReviewResult(
                decision=Decision.CONFIRM,
                sensitivity=Sensitivity.NORMAL,
                reason="自动记忆已关闭",
            )
        return ReviewResult(
            decision=Decision.AUTO_SAVE,
            sensitivity=Sensitivity.NORMAL,
            reason="低风险，按规则自动保存",
        )

    # 兜底：未知组合一律走确认
    return ReviewResult(
        decision=Decision.CONFIRM,
        sensitivity=Sensitivity.NORMAL,
        reason="未匹配到自动保存规则",
    )
