"""
MCP Server 数据加载：从 JSON 文件懒加载订单、物流、退款规则数据。
"""
import json
import os
from typing import Optional

from mcp_server.models import (
    Order, OrderStatus, LogisticsInfo, LogisticsStatus,
    LogisticsEvent, RefundRule,
)
from utils.path_tool import get_abs_path
from utils.config_handler import mcp_conf

_orders_cache: dict[str, Order] = {}
_logistics_cache: dict[str, LogisticsInfo] = {}
_refund_rules_cache: list[RefundRule] = []


def load_orders() -> dict[str, Order]:
    """懒加载订单数据，按 order_id 索引。"""
    if _orders_cache:
        return _orders_cache

    data_path = get_abs_path(mcp_conf["orders_data_path"])
    if not os.path.exists(data_path):
        return {}

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    for item in raw_list:
        order = Order(
            order_id=item["order_id"],
            user_id=item["user_id"],
            product_name=item["product_name"],
            product_model=item["product_model"],
            quantity=item["quantity"],
            amount=item["amount"],
            status=OrderStatus(item["status"]),
            created_at=item["created_at"],
            paid_at=item.get("paid_at", ""),
            address=item.get("address", ""),
        )
        _orders_cache[order.order_id] = order

    return _orders_cache


def load_logistics() -> dict[str, LogisticsInfo]:
    """懒加载物流数据，按 order_id 索引。"""
    if _logistics_cache:
        return _logistics_cache

    data_path = get_abs_path(mcp_conf["logistics_data_path"])
    if not os.path.exists(data_path):
        return {}

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    for item in raw_list:
        events = [
            LogisticsEvent(
                timestamp=evt["timestamp"],
                status=evt["status"],
                location=evt["location"],
                description=evt["description"],
            )
            for evt in item.get("events", [])
        ]
        info = LogisticsInfo(
            order_id=item["order_id"],
            carrier=item["carrier"],
            tracking_number=item["tracking_number"],
            status=LogisticsStatus(item["status"]),
            shipped_at=item.get("shipped_at", ""),
            events=events,
        )
        _logistics_cache[info.order_id] = info

    return _logistics_cache


def load_refund_rules() -> list[RefundRule]:
    """懒加载退款规则数据。"""
    if _refund_rules_cache:
        return _refund_rules_cache

    data_path = get_abs_path(mcp_conf["refund_rules_path"])
    if not os.path.exists(data_path):
        return []

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    for item in raw_list:
        rule = RefundRule(
            rule_id=item["rule_id"],
            name=item["name"],
            description=item["description"],
            conditions=item["conditions"],
            time_limit_days=item["time_limit_days"],
            exceptions=item["exceptions"],
            requires_photos=item.get("requires_photos", False),
        )
        _refund_rules_cache.append(rule)

    return _refund_rules_cache


def get_order(order_id: str) -> Optional[Order]:
    """根据订单号查询单个订单。"""
    return load_orders().get(order_id.strip())


def get_logistics(order_id: str) -> Optional[LogisticsInfo]:
    """根据订单号查询物流信息。"""
    return load_logistics().get(order_id.strip())


def get_refund_rules_text() -> str:
    """将退款规则格式化为可读文本，用于注入系统提示词。"""
    rules = load_refund_rules()
    if not rules:
        return "暂无退款规则信息。"

    parts = ["退款政策规则："]
    for rule in rules:
        parts.append(f"\n【{rule.name}】")
        parts.append(f"规则编号：{rule.rule_id}")
        parts.append(f"说明：{rule.description}")
        parts.append(f"适用条件：{'；'.join(rule.conditions)}")
        parts.append(f"时间限制：签收后{rule.time_limit_days}天内")
        if rule.exceptions:
            parts.append(f"例外情况：{'；'.join(rule.exceptions)}")
        if rule.requires_photos:
            parts.append("需要提供照片凭证")
    return "\n".join(parts)
