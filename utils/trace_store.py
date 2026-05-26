"""
Trace 持久化存储模块。

将 TraceRecord 按日期存储为 JSONL 文件（每行一个 JSON 对象），
支持按 session_id 或日期查询。
"""

import json
import os
from glob import glob
from typing import Optional

from utils.path_tool import get_abs_path
from utils.trace_context import (
    RAGDocScore,
    RAGTrace,
    SentimentTrace,
    ToolCallTrace,
    TraceRecord,
)


TRACE_DIR = get_abs_path("storage/traces")


def _ensure_dir() -> None:
    os.makedirs(TRACE_DIR, exist_ok=True)


def _trace_to_dict(trace: TraceRecord) -> dict:
    """将 TraceRecord 序列化为字典。"""
    result = {
        "trace_id": trace.trace_id,
        "session_id": trace.session_id,
        "timestamp": trace.timestamp,
        "query": trace.query,
        "sentiment": None,
        "tool_calls": [],
        "rag": None,
        "llm_latency_ms": trace.llm_latency_ms,
        "combined_confidence": trace.combined_confidence,
        "follow_up_triggered": trace.follow_up_triggered,
        "follow_up_action": trace.follow_up_action,
    }

    if trace.sentiment:
        result["sentiment"] = {
            "score": trace.sentiment.score,
            "level": trace.sentiment.level,
            "label": trace.sentiment.label,
            "need_human": trace.sentiment.need_human,
            "matched_rules": trace.sentiment.matched_rules,
            "confidence": trace.sentiment.confidence,
        }

    for tc in trace.tool_calls:
        result["tool_calls"].append({
            "tool_name": tc.tool_name,
            "args": tc.args,
            "success": tc.success,
            "duration_ms": tc.duration_ms,
            "error_message": tc.error_message,
        })

    if trace.rag:
        result["rag"] = {
            "query": trace.rag.query,
            "expanded_query": trace.rag.expanded_query,
            "candidate_count": trace.rag.candidate_count,
            "selected_count": trace.rag.selected_count,
            "top_rerank_score": trace.rag.top_rerank_score,
            "avg_rerank_score": trace.rag.avg_rerank_score,
            "doc_scores": [
                {
                    "source": ds.source,
                    "page": ds.page,
                    "chunk_index": ds.chunk_index,
                    "relevance_score": ds.relevance_score,
                    "rerank_score": ds.rerank_score,
                }
                for ds in trace.rag.doc_scores
            ],
            "confidence": trace.rag.confidence,
        }

    return result


def _dict_to_trace(d: dict) -> TraceRecord:
    """将字典反序列化为 TraceRecord。"""
    sentiment = None
    if d.get("sentiment"):
        s = d["sentiment"]
        sentiment = SentimentTrace(
            score=s["score"],
            level=s["level"],
            label=s["label"],
            need_human=s["need_human"],
            matched_rules=s.get("matched_rules", []),
            confidence=s.get("confidence", 0.0),
        )

    tool_calls = []
    for tc in d.get("tool_calls", []):
        tool_calls.append(ToolCallTrace(
            tool_name=tc["tool_name"],
            args=tc.get("args", {}),
            success=tc["success"],
            duration_ms=tc["duration_ms"],
            error_message=tc.get("error_message"),
        ))

    rag = None
    if d.get("rag"):
        r = d["rag"]
        rag = RAGTrace(
            query=r["query"],
            expanded_query=r["expanded_query"],
            candidate_count=r["candidate_count"],
            selected_count=r["selected_count"],
            top_rerank_score=r["top_rerank_score"],
            avg_rerank_score=r["avg_rerank_score"],
            doc_scores=[
                RAGDocScore(
                    source=ds["source"],
                    page=ds.get("page"),
                    chunk_index=ds.get("chunk_index"),
                    relevance_score=ds["relevance_score"],
                    rerank_score=ds["rerank_score"],
                )
                for ds in r.get("doc_scores", [])
            ],
            confidence=r.get("confidence", 0.0),
        )

    return TraceRecord(
        trace_id=d["trace_id"],
        session_id=d["session_id"],
        timestamp=d["timestamp"],
        query=d["query"],
        sentiment=sentiment,
        tool_calls=tool_calls,
        rag=rag,
        llm_latency_ms=d.get("llm_latency_ms"),
        combined_confidence=d.get("combined_confidence", 0.0),
        follow_up_triggered=d.get("follow_up_triggered", False),
        follow_up_action=d.get("follow_up_action"),
    )


def save_trace(trace: TraceRecord) -> None:
    """保存单条 Trace 到当日 JSONL 文件。"""
    _ensure_dir()
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(TRACE_DIR, f"{today}.jsonl")

    trace_dict = _trace_to_dict(trace)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")


def load_traces(session_id: str, date: Optional[str] = None) -> list[TraceRecord]:
    """按 session_id 查询历史 Trace，可选按日期过滤。"""
    results = []

    if date:
        files = [os.path.join(TRACE_DIR, f"{date}.jsonl")]
    else:
        files = sorted(glob(os.path.join(TRACE_DIR, "*.jsonl")))

    for file_path in files:
        if not os.path.exists(file_path):
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                trace_dict = json.loads(line)
                if trace_dict.get("session_id") == session_id:
                    results.append(_dict_to_trace(trace_dict))

    return sorted(results, key=lambda t: t.timestamp)


def load_traces_by_date(date: str) -> list[TraceRecord]:
    """加载指定日期的所有 Trace。"""
    file_path = os.path.join(TRACE_DIR, f"{date}.jsonl")
    if not os.path.exists(file_path):
        return []

    results = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            results.append(_dict_to_trace(json.loads(line)))

    return results
