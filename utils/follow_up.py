"""
低置信度追问模块。

当综合置信度低于阈值时，生成追问提示引导用户提供更多信息。
"""

import random
from dataclasses import dataclass
from typing import Optional

from utils.confidence import ConfidenceResult
from utils.trace_context import TraceRecord


@dataclass
class FollowUpPrompt:
    """追问提示"""
    question: str
    dimension: str
    reason: str
    original_query: str


# 追问模板：按弱维度分类
FOLLOW_UP_TEMPLATES = {
    "rag_relevance": [
        "关于"{query}"，我想确认一下您的具体情况：是遇到了故障问题，还是想了解选购建议？",
        "关于"{query}"，能否具体描述一下遇到的问题？比如型号、故障现象等。",
    ],
    "rag_coverage": [
        "您的问题涉及范围较广，能否告诉我更多细节？比如具体型号或遇到的现象。",
        "为了更准确地回答"{query}"，您能否提供更多背景信息？",
    ],
    "sentiment": [
        "理解您的心情。为更好地帮助您，能否具体描述一下遇到的问题？",
        "您的问题我已收到，能否详细说明一下具体情况？",
    ],
}

# 通用追问模板
DEFAULT_FOLLOW_UP = [
    "关于您的问题，我想确认一下：您最想了解的是哪个方面？",
    "为了更准确地回答，能否请您补充更多细节？",
]


def should_follow_up(
    confidence: ConfidenceResult,
    config: dict,
    follow_up_round: int = 0,
) -> bool:
    """
    判断是否需要追问。

    条件：
    1. 追问功能启用
    2. 未超过最大追问次数
    3. 综合置信度低于阈值
    """
    conf_config = config.get("confidence", {})

    if not conf_config.get("enabled", True):
        return False

    max_rounds = conf_config.get("max_follow_up_rounds", 1)
    if follow_up_round >= max_rounds:
        return False

    threshold = conf_config.get("follow_up_threshold", 0.45)
    return confidence.combined < threshold


def generate_follow_up(
    trace: TraceRecord,
    confidence: ConfidenceResult,
) -> Optional[FollowUpPrompt]:
    """
    根据置信度最弱维度生成追问内容。

    策略：
    1. 找到得分最低的维度
    2. 根据维度类型选择模板
    3. 填充用户原始query生成追问
    """
    if not confidence.dimensions:
        # 无维度信息，使用通用追问
        question = random.choice(DEFAULT_FOLLOW_UP)
        return FollowUpPrompt(
            question=question,
            dimension="unknown",
            reason="置信度较低",
            original_query=trace.query,
        )

    # 找到得分最低的维度
    weakest = min(confidence.dimensions, key=lambda d: d.score)

    # 选择模板
    templates = FOLLOW_UP_TEMPLATES.get(weakest.dimension, DEFAULT_FOLLOW_UP)
    template = random.choice(templates)

    # 填充query
    short_query = trace.query[:20] + ("..." if len(trace.query) > 20 else "")
    question = template.replace("{query}", short_query)

    return FollowUpPrompt(
        question=question,
        dimension=weakest.dimension,
        reason=weakest.reason,
        original_query=trace.query,
    )
