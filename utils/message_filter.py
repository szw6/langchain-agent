"""
冗余信息过滤模块。

提供对话消息的去重、填充词移除和近似重复检测功能。
纯函数实现，无LLM调用。
"""

import re
from typing import Optional


# 常见填充词/确认词
FILLER_PATTERNS = {
    r"^(你好|您好|嗨|哈喽|hello|hi|hey)$",
    r"^(好的?|嗯|哦|噢|OK|ok|知道了|明白|了解|收到|谢谢|感谢|对|是的?|可以)$",
    r"^(好的收到|明白了|知道了|没问题)$",
}


def _bigram_set(text: str) -> set[str]:
    """计算字符二元组集合，用于Jaccard相似度计算。"""
    text = text.strip().lower()
    if len(text) < 2:
        return {text}
    return {text[i:i+2] for i in range(len(text) - 1)}


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """计算两个集合的Jaccard相似度。"""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _is_filler(text: str, filler_patterns: Optional[list[str]] = None) -> bool:
    """检查消息是否为填充词/确认词。"""
    text = text.strip()
    if not text:
        return True

    patterns = filler_patterns or FILLER_PATTERNS
    for pattern in patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    return False


def _is_exact_duplicate(messages: list[dict], index: int) -> bool:
    """检查指定位置的消息是否在后面有完全相同的重复。"""
    if index >= len(messages) - 1:
        return False

    current_content = messages[index].get("content", "").strip()
    if not current_content:
        return False

    # 检查后面是否有相同内容的消息
    for later_msg in messages[index + 1:]:
        later_content = later_msg.get("content", "").strip()
        if current_content == later_content:
            return True
    return False


def _find_similar_message(
    messages: list[dict],
    index: int,
    threshold: float = 0.7,
) -> Optional[int]:
    """
    查找与指定位置消息近似重复的后续消息。

    返回相似消息的索引，如果没有找到返回None。
    """
    if index >= len(messages) - 1:
        return None

    current_content = messages[index].get("content", "").strip()
    current_bigrams = _bigram_set(current_content)

    for i in range(index + 1, len(messages)):
        later_content = messages[i].get("content", "").strip()
        later_bigrams = _bigram_set(later_content)

        similarity = _jaccard_similarity(current_bigrams, later_bigrams)
        if similarity >= threshold:
            return i

    return None


def filter_redundant_messages(
    messages: list[dict],
    jaccard_threshold: float = 0.7,
    enable_filler_removal: bool = True,
    filler_patterns: Optional[list[str]] = None,
) -> list[dict]:
    """
    过滤冗余消息，保留对话流程。

    处理步骤：
    1. 移除填充词/确认词
    2. 移除精确重复（保留最后一条）
    3. 移除近似重复（保留较新的）

    Args:
        messages: 原始消息列表
        jaccard_threshold: 近似重复检测阈值
        enable_filler_removal: 是否启用填充词移除
        filler_patterns: 自定义填充词正则模式列表

    Returns:
        过滤后的消息列表
    """
    if not messages:
        return []

    filtered = []
    skip_indices = set()

    for i, message in enumerate(messages):
        if i in skip_indices:
            continue

        content = (message.get("content") or "").strip()
        role = message.get("role", "")

        # 步骤1: 填充词移除（仅对user消息）
        if enable_filler_removal and role == "user" and _is_filler(content, filler_patterns):
            continue

        # 步骤2: 精确重复检测
        if _is_exact_duplicate(messages, i):
            continue

        # 步骤3: 近似重复检测
        similar_idx = _find_similar_message(messages, i, jaccard_threshold)
        if similar_idx is not None:
            # 标记相似消息为跳过（保留当前，跳过后面的）
            skip_indices.add(similar_idx)
            continue

        filtered.append(message)

    return filtered


def remove_consecutive_duplicates(messages: list[dict]) -> list[dict]:
    """移除连续重复的消息。"""
    if not messages:
        return []

    result = [messages[0]]
    for message in messages[1:]:
        prev_content = result[-1].get("content", "").strip()
        curr_content = message.get("content", "").strip()
        if prev_content != curr_content:
            result.append(message)
    return result
