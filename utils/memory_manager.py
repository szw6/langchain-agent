"""
会话记忆管理器。

提供会话压缩、摘要生成和事实提取功能。
"""

import re
from datetime import datetime
from typing import Optional

from model.factory import get_chat_model
from utils.message_filter import filter_redundant_messages


class SessionMemoryManager:
    """管理会话记忆：压缩、摘要生成、事实提取。"""

    # 常见城市列表
    COMMON_CITIES = [
        "北京", "上海", "广州", "深圳", "杭州", "苏州", "南京", "成都", "重庆", "天津",
        "武汉", "西安", "长沙", "青岛", "宁波", "厦门", "郑州", "合肥", "福州", "济南",
    ]
    INVALID_CITY_VALUES = {"哪个城市", "什么城市", "哪座城市", "哪个市", "哪里", "哪儿"}

    # 产品类型关键词
    PRODUCT_KEYWORDS = ["扫地机器人", "扫拖一体", "扫拖机器人", "洗地机"]

    # 常见问题关键词
    CONCERN_KEYWORDS = [
        "水痕", "不回充", "迷路", "漏扫", "噪音", "缠头发", "不出水", "卡住",
        "不充电", "找不到", "无法", "故障", "问题", "坏了", "维修",
    ]

    def __init__(self, config: dict):
        """
        初始化记忆管理器。

        Args:
            config: 记忆配置字典，从 config/memory.yaml 加载
        """
        memory_config = config.get("memory", {})
        self.token_threshold = memory_config.get("token_threshold", 3000)
        self.message_threshold = memory_config.get("message_threshold", 20)
        self.keep_recent_count = memory_config.get("keep_recent_count", 6)
        self.max_summary_length = memory_config.get("max_summary_length", 800)
        self.min_messages_before_compress = memory_config.get("min_messages_before_compress", 4)
        self.enable_redundancy_filter = memory_config.get("enable_redundancy_filter", True)
        self.jaccard_threshold = memory_config.get("redundancy_jaccard_threshold", 0.7)

        # 延迟初始化LLM，避免循环导入
        self._model = None

    @property
    def model(self):
        """延迟加载LLM模型。"""
        if self._model is None:
            self._model = get_chat_model()
        return self._model

    def estimate_tokens(self, messages: list[dict]) -> int:
        """
        估算消息列表的token数量。

        使用简单的启发式方法：
        - 中文字符：约1.5 token/字符
        - 英文单词：约1 token/词
        - 标点符号：约0.5 token/个
        """
        total_chars = 0
        for message in messages:
            content = (message.get("content") or "").strip()
            if not content:
                continue

            # 统计中文字符
            chinese_chars = len(re.findall(r'[一-鿿]', content))
            # 统计英文单词
            english_words = len(re.findall(r'[a-zA-Z]+', content))
            # 统计标点
            punctuation = len(re.findall(r'[^\w\s一-鿿]', content))

            total_chars += int(chinese_chars * 1.5) + english_words + int(punctuation * 0.5)

        return total_chars

    def should_compress(self, messages: list[dict]) -> bool:
        """
        判断是否应该触发压缩。

        满足任一条件即触发：
        1. 消息数量超过阈值
        2. Token数量超过阈值
        3. 消息数量达到最小压缩要求
        """
        if len(messages) < self.min_messages_before_compress:
            return False

        if len(messages) >= self.message_threshold:
            return True

        token_count = self.estimate_tokens(messages)
        if token_count >= self.token_threshold:
            return True

        return False

    def generate_summary(
        self,
        messages_to_summarize: list[dict],
        existing_summary: str = "",
    ) -> str:
        """
        调用LLM生成对话摘要。

        Args:
            messages_to_summarize: 需要被压缩的消息列表
            existing_summary: 已有的摘要（用于增量更新）

        Returns:
            生成的摘要文本
        """
        if not messages_to_summarize:
            return existing_summary

        # 构建消息文本
        messages_text = []
        for msg in messages_to_summarize:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = (msg.get("content") or "").strip()
            if content:
                messages_text.append(f"{role}: {content}")

        messages_text_str = "\n".join(messages_text)

        # 构建已有摘要部分
        existing_summary_section = ""
        if existing_summary:
            existing_summary_section = f"已有摘要：\n{existing_summary}\n\n请在此基础上更新摘要。"

        # 读取提示词模板
        prompt_template = self._load_summary_prompt()

        # 填充模板
        prompt = prompt_template.format(
            max_length=self.max_summary_length,
            existing_summary_section=existing_summary_section,
            messages_text=messages_text_str,
        )

        # 调用LLM生成摘要
        try:
            response = self.model.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            # 摘要生成失败时，返回已有摘要或空字符串
            print(f"摘要生成失败: {e}")
            return existing_summary

    def _load_summary_prompt(self) -> str:
        """加载摘要生成提示词模板。"""
        from utils.path_tool import get_abs_path

        prompt_path = get_abs_path("prompts/memory_summary.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            # 返回默认提示词
            return """请将以下对话历史压缩为一段简洁的摘要，保留关键信息。
摘要控制在{max_length}字以内，使用中文。

{existing_summary_section}

对话历史：
{messages_text}

请输出摘要："""

    def extract_facts(
        self,
        messages: list[dict],
        existing_facts: Optional[dict] = None,
    ) -> dict:
        """
        从消息中提取结构化事实。

        提取内容包括：
        - 城市/位置
        - 用户ID
        - 产品类型
        - 主要关注点

        Args:
            messages: 消息列表
            existing_facts: 已有的事实字典

        Returns:
            更新后的事实字典
        """
        facts = dict(existing_facts) if existing_facts else {}

        for message in messages:
            content = (message.get("content") or "").strip()
            if not content:
                continue

            # 提取城市
            for city in self.COMMON_CITIES:
                if city in content:
                    facts["city"] = city

            city_match = re.search(
                r"(?:在|住在|来自|位于)([^\s，。！？,.!?]{2,12}(?:市|县|区|北京|上海|广州|深圳|杭州|苏州|南京|成都|重庆|天津|武汉|西安|长沙|青岛|宁波|厦门|郑州|合肥|福州|济南))",
                content,
            )
            if city_match:
                candidate_city = city_match.group(1)
                if candidate_city not in self.INVALID_CITY_VALUES:
                    facts["city"] = candidate_city

            # 提取用户ID
            user_id_match = re.search(r"(?:用户ID|ID|id)[：:\s]*([0-9]{3,})", content)
            if user_id_match:
                facts["user_id"] = user_id_match.group(1)

            # 提取产品类型
            for keyword in self.PRODUCT_KEYWORDS:
                if keyword in content:
                    facts["product_type"] = keyword

            # 提取主要关注点（仅从用户消息提取）
            if message.get("role") == "user":
                for concern in self.CONCERN_KEYWORDS:
                    if concern in content:
                        facts["primary_concern"] = concern

            # 提取用户名
            name_match = re.search(r"(?:我叫|我是|名字是|称呼我)([^\s，。！？,.!?]{2,6})", content)
            if name_match:
                facts["user_name"] = name_match.group(1)

        return facts

    def compress_messages(
        self,
        messages: list[dict],
        existing_summary: str = "",
        existing_facts: Optional[dict] = None,
    ) -> tuple[str, list[dict], dict]:
        """
        压缩消息列表，生成摘要并提取事实。

        Args:
            messages: 原始消息列表
            existing_summary: 已有摘要
            existing_facts: 已有事实

        Returns:
            (new_summary, compressed_messages, extracted_facts)
        """
        # 保留最近N条消息
        recent_count = min(self.keep_recent_count, len(messages))
        recent_messages = messages[-recent_count:]
        old_messages = messages[:-recent_count] if recent_count < len(messages) else []

        # 生成摘要
        new_summary = existing_summary
        if old_messages:
            new_summary = self.generate_summary(old_messages, existing_summary)

        # 提取事实（从所有消息中提取）
        extracted_facts = self.extract_facts(messages, existing_facts)

        return new_summary, recent_messages, extracted_facts

    def prepare_messages_for_agent(
        self,
        messages: list[dict],
        session_memory: Optional[dict] = None,
    ) -> tuple[list[dict], Optional[dict]]:
        """
        主入口：准备发送给Agent的消息。

        处理流程：
        1. 冗余过滤
        2. 检查是否需要压缩
        3. 如果需要，执行压缩
        4. 返回处理后的消息和更新的记忆

        Args:
            messages: 原始消息列表
            session_memory: 会话记忆（可选）

        Returns:
            (managed_messages, updated_memory)
        """
        if not messages:
            return messages, session_memory

        # 步骤1: 冗余过滤
        if self.enable_redundancy_filter:
            filtered_messages = filter_redundant_messages(
                messages,
                jaccard_threshold=self.jaccard_threshold,
            )
        else:
            filtered_messages = messages

        # 获取已有记忆
        existing_summary = ""
        existing_facts = {}
        if session_memory:
            existing_summary = session_memory.get("summary", "")
            existing_facts = session_memory.get("facts", {})

        # 步骤2: 检查是否需要压缩
        if not self.should_compress(filtered_messages):
            # 不需要压缩，只提取事实
            updated_facts = self.extract_facts(filtered_messages, existing_facts)
            if updated_facts != existing_facts:
                updated_memory = {
                    "summary": existing_summary,
                    "facts": updated_facts,
                    "last_compressed_at": session_memory.get("last_compressed_at", ""),
                    "compression_count": session_memory.get("compression_count", 0),
                }
                return filtered_messages, updated_memory
            return filtered_messages, session_memory

        # 步骤3: 执行压缩
        new_summary, recent_messages, extracted_facts = self.compress_messages(
            filtered_messages,
            existing_summary,
            existing_facts,
        )

        # 构建更新后的记忆
        updated_memory = {
            "summary": new_summary,
            "summary_message_count": len(recent_messages),
            "facts": extracted_facts,
            "last_compressed_at": datetime.now().isoformat(timespec="seconds"),
            "total_original_messages": len(filtered_messages),
            "compression_count": session_memory.get("compression_count", 0) + 1 if session_memory else 1,
        }

        return recent_messages, updated_memory
