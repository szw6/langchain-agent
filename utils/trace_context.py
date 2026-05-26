"""
Trace 上下文管理模块。

使用 contextvars 实现请求级别的 Trace 数据传递，
各模块无需修改函数签名即可写入 Trace 数据。
"""

import contextvars
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class SentimentTrace:
    """情绪分析追踪"""
    score: int
    level: str
    label: str
    need_human: bool
    matched_rules: list[str]
    confidence: float = 0.0


@dataclass
class RAGDocScore:
    """单个文档的检索分数"""
    source: str
    page: Optional[int]
    chunk_index: Optional[int]
    relevance_score: float
    rerank_score: float


@dataclass
class RAGTrace:
    """RAG检索追踪"""
    query: str
    expanded_query: str
    candidate_count: int
    selected_count: int
    top_rerank_score: float
    avg_rerank_score: float
    doc_scores: list[RAGDocScore] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ToolCallTrace:
    """单次工具调用的追踪记录"""
    tool_name: str
    args: dict
    success: bool
    duration_ms: float
    error_message: Optional[str] = None


@dataclass
class TraceRecord:
    """单轮对话的完整追踪"""
    trace_id: str
    session_id: str
    timestamp: str
    query: str
    sentiment: Optional[SentimentTrace] = None
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    rag: Optional[RAGTrace] = None
    llm_latency_ms: Optional[float] = None
    combined_confidence: float = 0.0
    follow_up_triggered: bool = False
    follow_up_action: Optional[str] = None


# ── ContextVar 管理 ───────────────────────────────────────

_current_trace: contextvars.ContextVar[Optional[TraceRecord]] = contextvars.ContextVar(
    "current_trace", default=None
)


def start_trace(session_id: str, query: str) -> TraceRecord:
    """创建新的 TraceRecord 并绑定到当前上下文。"""
    trace = TraceRecord(
        trace_id=uuid.uuid4().hex,
        session_id=session_id,
        timestamp=datetime.now().isoformat(timespec="seconds"),
        query=query,
    )
    _current_trace.set(trace)
    return trace


def get_trace() -> Optional[TraceRecord]:
    """获取当前 Trace（不在 trace 上下文中时返回 None）。"""
    return _current_trace.get()


def end_trace() -> Optional[TraceRecord]:
    """获取最终 Trace 并清除上下文变量。"""
    trace = _current_trace.get()
    _current_trace.set(None)
    return trace


# ── 便捷写入函数 ─────────────────────────────────────────

def record_sentiment(data: dict) -> None:
    """将情绪分析结果写入当前 Trace。"""
    trace = get_trace()
    if trace is None:
        return
    trace.sentiment = SentimentTrace(
        score=data.get("score", 0),
        level=data.get("level", "neutral"),
        label=data.get("label", "中性"),
        need_human=data.get("need_human", False),
        matched_rules=data.get("matched_rules", []),
    )


def record_tool_call(
    tool_name: str,
    args: dict,
    success: bool,
    duration_ms: float,
    error: Optional[str] = None,
) -> None:
    """追加工具调用记录到当前 Trace。"""
    trace = get_trace()
    if trace is None:
        return
    trace.tool_calls.append(ToolCallTrace(
        tool_name=tool_name,
        args=args,
        success=success,
        duration_ms=duration_ms,
        error_message=error,
    ))


def record_rag(
    query: str,
    expanded_query: str,
    candidate_count: int,
    selected_count: int,
    top_rerank_score: float,
    avg_rerank_score: float,
    doc_scores: list[dict],
) -> None:
    """将 RAG 检索数据写入当前 Trace。"""
    trace = get_trace()
    if trace is None:
        return
    trace.rag = RAGTrace(
        query=query,
        expanded_query=expanded_query,
        candidate_count=candidate_count,
        selected_count=selected_count,
        top_rerank_score=top_rerank_score,
        avg_rerank_score=avg_rerank_score,
        doc_scores=[
            RAGDocScore(
                source=d.get("source", ""),
                page=d.get("page"),
                chunk_index=d.get("chunk_index"),
                relevance_score=d.get("relevance_score", 0),
                rerank_score=d.get("rerank_score", 0),
            )
            for d in doc_scores
        ],
    )


def record_llm_latency(ms: float) -> None:
    """记录 LLM 调用耗时。"""
    trace = get_trace()
    if trace:
        trace.llm_latency_ms = ms
