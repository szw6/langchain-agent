"""
置信度计算模块。

基于 Trace 数据计算情绪置信度、RAG 置信度和综合置信度，
用于判断回答质量和是否需要追问用户。
"""

from dataclasses import dataclass, field
from typing import Optional

from utils.trace_context import RAGTrace, SentimentTrace, TraceRecord


@dataclass
class DimensionDetail:
    """置信度维度详情"""
    dimension: str     # "sentiment" | "rag_relevance" | "rag_coverage"
    score: float
    label: str
    reason: str


@dataclass
class ConfidenceResult:
    """置信度计算结果"""
    sentiment_confidence: float
    rag_confidence: float
    combined: float
    dimensions: list[DimensionDetail] = field(default_factory=list)


def compute_sentiment_confidence(
    sentiment: Optional[SentimentTrace],
    config: dict,
) -> tuple[float, DimensionDetail]:
    """
    计算情绪置信度。

    规则：
    - need_human=True => 0.5（情绪检测正常，但需转人工）
    - score ∈ [-10, 10] => 0.9（中性，意图清晰）
    - score > 0（负面）=> max(0.1, 0.8 - score/100)
    - score < 0（正面）=> 0.85（正向意图清晰）
    - 无规则命中且score=0 => 0.7（无信号，假设中性）
    """
    if sentiment is None:
        return 0.5, DimensionDetail(
            dimension="sentiment",
            score=0.5,
            label="未检测",
            reason="未进行情绪分析",
        )

    score = sentiment.score
    neutral_range = config.get("sentiment", {}).get("neutral_score_range", [-10, 10])

    if sentiment.need_human:
        conf = 0.5
        reason = "情绪检测正常，需转人工介入"
    elif neutral_range[0] <= score <= neutral_range[1]:
        conf = 0.9
        reason = f"情绪中性（分数{score}），意图清晰"
    elif score > 0:
        conf = max(0.1, 0.8 - score / 100)
        reason = f"负面情绪（分数{score}），可能影响问题表达"
    elif score < 0:
        conf = 0.85
        reason = f"正面情绪（分数{score}），意图清晰"
    else:
        conf = 0.7
        reason = "无情绪信号，假设中性"

    label = "高" if conf >= 0.7 else ("中" if conf >= 0.4 else "低")
    return conf, DimensionDetail(
        dimension="sentiment",
        score=conf,
        label=f"情绪置信度: {label}",
        reason=reason,
    )


def compute_rag_confidence(
    rag: Optional[RAGTrace],
    config: dict,
) -> tuple[float, list[DimensionDetail]]:
    """
    计算 RAG 置信度。

    规则：
    - base = top_rerank_score * 0.6 + avg_rerank_score * 0.4
    - candidate_count < 3 => base *= 0.7
    - top_rerank_score < low_relevance_threshold => base *= 0.5
    """
    rag_config = config.get("rag", {})
    low_threshold = rag_config.get("low_relevance_threshold", 0.25)
    top_weight = rag_config.get("top_score_weight", 0.6)
    avg_weight = rag_config.get("avg_score_weight", 0.4)

    details = []

    if rag is None:
        return 0.5, [DimensionDetail(
            dimension="rag_relevance",
            score=0.5,
            label="RAG置信度: 未检索",
            reason="未执行知识库检索",
        )]

    # 基础分数
    base = rag.top_rerank_score * top_weight + rag.avg_rerank_score * avg_weight

    details.append(DimensionDetail(
        dimension="rag_relevance",
        score=rag.top_rerank_score,
        label=f"最高相关性: {rag.top_rerank_score:.2f}",
        reason=f"检索到{rag.candidate_count}个候选，入选{rag.selected_count}个",
    ))

    # 候选数量调整
    if rag.candidate_count < 3:
        base *= 0.7
        details.append(DimensionDetail(
            dimension="rag_coverage",
            score=0.7,
            label="候选不足",
            reason=f"仅检索到{rag.candidate_count}个候选，覆盖度低",
        ))
    else:
        details.append(DimensionDetail(
            dimension="rag_coverage",
            score=min(1.0, rag.candidate_count / 10),
            label=f"候选覆盖: {rag.candidate_count}个",
            reason=f"检索到{rag.candidate_count}个候选，覆盖度充足",
        ))

    # 低相关性调整
    if rag.top_rerank_score < low_threshold:
        base *= 0.5
        details.append(DimensionDetail(
            dimension="rag_relevance",
            score=0.5,
            label="相关性偏低",
            reason=f"最高相关性{rag.top_rerank_score:.2f}低于阈值{low_threshold}",
        ))

    conf = max(0.0, min(1.0, base))
    return conf, details


def compute_confidence(
    trace: TraceRecord,
    config: dict,
) -> ConfidenceResult:
    """
    计算综合置信度。

    综合置信度 = sentiment_confidence * 0.3 + rag_confidence * 0.7
    """
    weights = config.get("confidence", {}).get("weights", {})
    w_sentiment = weights.get("sentiment", 0.3)
    w_rag = weights.get("rag", 0.7)

    sentiment_conf, sentiment_detail = compute_sentiment_confidence(
        trace.sentiment, config.get("confidence", {})
    )
    rag_conf, rag_details = compute_rag_confidence(
        trace.rag, config.get("confidence", {})
    )

    combined = sentiment_conf * w_sentiment + rag_conf * w_rag

    dimensions = [sentiment_detail] + rag_details

    return ConfidenceResult(
        sentiment_confidence=sentiment_conf,
        rag_confidence=rag_conf,
        combined=combined,
        dimensions=dimensions,
    )
