"""
情绪识别规则引擎
=================
基于 YAML 配置的关键词 + 正则规则，对用户 query 进行情绪评分。

使用方式：
    engine = SentimentEngine()
    result = engine.analyze("你们这破机器又坏了！")
    # result = {
    #     "score": 60,
    #     "level": "negative_strong",
    #     "label": "强烈负面",
    #     "need_human": False,
    #     "action": "soft_answer",
    #     "matched_rules": [...],
    #     "sentiment_prompt": "..."
    # }
"""
from __future__ import annotations

import os
import re
from typing import Any

import yaml

from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class SentimentEngine:
    """YAML 驱动的情绪规则引擎。"""

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = get_abs_path("config/sentiment_rules.yaml")
        self._config_path = config_path
        self._config: dict[str, Any] = {}
        self._load_config()

    # ── 配置加载 ────────────────────────────────────────────

    def _load_config(self) -> None:
        if not os.path.exists(self._config_path):
            logger.warning(f"情绪规则配置文件不存在: {self._config_path}，引擎将返回中性结果")
            self._config = {}
            return
        with open(self._config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}
        logger.info(f"情绪规则引擎加载完成: {self._config_path}")

    def reload(self) -> None:
        """热重载规则文件。"""
        self._load_config()

    # ── 分析入口 ────────────────────────────────────────────

    def analyze(self, query: str) -> dict[str, Any]:
        """
        对单条用户 query 做情绪分析。

        Returns:
            dict 包含 score / level / label / need_human / action /
                  matched_rules / sentiment_prompt
        """
        if not query or not query.strip():
            return self._neutral_result("空输入")

        text = query.strip()

        # 1. 优先检查 need_human 规则（命中即返回，不累计分数）
        need_human, nh_rules = self._check_need_human(text)
        if need_human:
            return {
                "score": 100,
                "level": "critical",
                "label": "需人工介入",
                "need_human": True,
                "action": "need_human",
                "matched_rules": nh_rules,
                "sentiment_prompt": "",
            }

        # 2. 累加计分规则
        score, matched_rules = self._calc_score(text)

        # 3. 判定等级
        level, label, action = self._classify(score)

        # 4. 生成情绪提示词片段
        sentiment_prompt = self._build_sentiment_prompt(label, score) if score > 0 else ""

        return {
            "score": score,
            "level": level,
            "label": label,
            "need_human": False,
            "action": action,
            "matched_rules": matched_rules,
            "sentiment_prompt": sentiment_prompt,
        }

    # ── need_human 规则检查 ─────────────────────────────────

    def _check_need_human(self, text: str) -> tuple[bool, list[str]]:
        rules = self._config.get("need_human_rules", [])
        matched: list[str] = []
        for rule in rules:
            if self._match_rule(text, rule):
                matched.append(rule.get("name", "unknown"))
                logger.info(f"[情绪引擎] need_human 命中规则: {rule.get('name')}, query={text[:60]}")
        return (len(matched) > 0, matched)

    # ── 计分规则 ─────────────────────────────────────────────

    def _calc_score(self, text: str) -> tuple[int, list[str]]:
        rules = self._config.get("scoring_rules", [])
        total = 0
        matched: list[str] = []
        for rule in rules:
            if self._match_rule(text, rule):
                s = rule.get("score", 0)
                total += s
                matched.append(f"{rule.get('name', 'unknown')}({'↑' if s > 0 else '↓'}{abs(s)})")
                logger.debug(f"[情绪引擎] 计分命中: {rule.get('name')} ({s:+d}), query={text[:60]}")
        return (total, matched)

    # ── 通用规则匹配 ─────────────────────────────────────────

    @staticmethod
    def _match_rule(text: str, rule: dict[str, Any]) -> bool:
        """对单条规则做关键词或正则匹配，任一命中即返回 True。"""
        # 关键词匹配（全词/子串）
        for kw in rule.get("keywords", []):
            if kw in text:
                return True
        # 正则匹配
        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, text):
                    return True
            except re.error as e:
                logger.warning(f"[情绪引擎] 正则编译失败: {pattern}, error={e}")
        return False

    # ── 等级判定 ─────────────────────────────────────────────

    def _classify(self, score: int) -> tuple[str, str, str]:
        """根据分数返回 (level, label, action)。"""
        levels = self._config.get("settings", {}).get("levels", {})
        # 按 min 降序排列，从高到低匹配
        sorted_levels = sorted(levels.items(), key=lambda x: x[1].get("min", 0), reverse=True)
        for level_name, cfg in sorted_levels:
            if score >= cfg.get("min", 0):
                return (level_name, cfg.get("label", "未知"), cfg.get("action", "normal_answer"))
        # 兜底
        return ("neutral", "中性", "normal_answer")

    # ── 情绪提示词 ───────────────────────────────────────────

    def _build_sentiment_prompt(self, label: str, score: int) -> str:
        tpl = self._config.get("sentiment_prompt_template", "")
        return tpl.replace("{label}", label).replace("{score}", str(score))

    # ── 工具方法 ─────────────────────────────────────────────

    @staticmethod
    def _neutral_result(reason: str) -> dict[str, Any]:
        return {
            "score": 0,
            "level": "neutral",
            "label": "中性",
            "need_human": False,
            "action": "normal_answer",
            "matched_rules": [],
            "sentiment_prompt": "",
        }

    def get_need_human_response(self) -> str:
        """返回人工介入时的固定回复文案。"""
        return self._config.get(
            "need_human_response",
            "您的问题已转接人工客服，请稍候。",
        )


# ── 模块级单例 ──────────────────────────────────────────────

_engine: SentimentEngine | None = None


def get_engine() -> SentimentEngine:
    """获取全局单例引擎。"""
    global _engine
    if _engine is None:
        _engine = SentimentEngine()
    return _engine


def analyze_sentiment(query: str) -> dict[str, Any]:
    """便捷函数：分析 query 情绪。"""
    return get_engine().analyze(query)
